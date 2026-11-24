"""Malla de tetraedros de la geometría REAL (no de vóxeles).

Mallador principal: **fTetWild** (Hu, Schneider, Wang, Zorin, Panozzo, "Fast
Tetrahedral Meshing in the Wild", ACM TOG 2020) a través de `pytetwild`. Está
diseñado para superficies imperfectas (auto-intersecciones, agujeros pequeños,
triángulos degenerados), justo lo que sale de un STL cualquiera o del marching
cubes de un diseño optimizado, y siempre termina.

Respaldo: **gmsh** (https://gmsh.info), mallando el volumen sobre la superficie
del STL llevada al tamaño pedido. gmsh necesita una superficie limpia y, con
algunas, el mallado no termina; por eso solo se usa si fTetWild no está disponible.
"""
from __future__ import annotations

import glob
import os
import sys
import tempfile
import threading
from typing import Optional

import numpy as np
import trimesh

_LOCK = threading.Lock()  # gmsh y fTetWild usan estado global: un mallado a la vez
_FTW = None
_DLL_HANDLES: list = []  # mantener vivas las rutas de DLL añadidas en Windows


def _load_ftetwild():
    """Carga el núcleo compilado de pytetwild SIN ejecutar el __init__ del paquete,
    que importa PyVista/VTK (≈100 MB que aquí no hacen falta)."""
    global _FTW
    if _FTW is not None:
        return _FTW or None
    import importlib.machinery
    import importlib.util

    dirs = []
    try:
        spec = importlib.util.find_spec("pytetwild")
        if spec and spec.submodule_search_locations:
            dirs += list(spec.submodule_search_locations)
    except Exception:
        pass
    base = getattr(sys, "_MEIPASS", None)  # ejecutable empaquetado con PyInstaller
    if base:
        dirs.append(os.path.join(base, "pytetwild"))
    for d in dirs:
        # En Windows la rueda trae DLLs (MPIR, runtime de MSVC) en "pytetwild.libs" que el
        # __init__ del paquete registra (parche de delvewheel); como no lo ejecutamos, se hace aquí.
        libs = os.path.abspath(os.path.join(d, os.pardir, "pytetwild.libs"))
        if os.name == "nt" and os.path.isdir(libs):
            try:
                _DLL_HANDLES.append(os.add_dll_directory(libs))
            except OSError:
                pass
        for path in glob.glob(os.path.join(d, "PyfTetWildWrapper*")):
            if not path.endswith((".so", ".pyd")):
                continue
            try:
                loader = importlib.machinery.ExtensionFileLoader("PyfTetWildWrapper", path)
                spec = importlib.util.spec_from_file_location("PyfTetWildWrapper", path, loader=loader)
                mod = importlib.util.module_from_spec(spec)
                loader.exec_module(mod)
                _FTW = mod
                return mod
            except Exception:
                continue
    _FTW = False
    return None


def available_meshers() -> list:
    out = []
    if _load_ftetwild() is not None:
        out.append("fTetWild")
    try:
        import gmsh  # noqa: F401

        out.append("gmsh")
    except Exception:
        pass
    return out


def default_mesh_size(mesh: trimesh.Trimesh, n_across: float = 20.0) -> float:
    """Tamaño de elemento por defecto: ~n elementos a lo largo de la dimensión mayor."""
    ext = mesh.bounds[1] - mesh.bounds[0]
    return float(max(ext) / n_across)


def tetrahedralize(mesh: trimesh.Trimesh, size: Optional[float] = None, max_nodes: int = 60000,
                   coarse: bool = False):
    """Devuelve (p, t): nodos (3, N) y tetraedros lineales (4, M) en mm, con orientación positiva.

    `size` es la longitud de arista objetivo (mm). `coarse=True` permite a fTetWild
    alejarse algo más de la superficie y engrosar la malla (útil para pandeo y modos,
    que son magnitudes globales). Si salen más de `max_nodes` nodos se repite con
    un tamaño mayor.
    """
    surf = mesh.copy()
    surf.merge_vertices()
    surf.update_faces(surf.nondegenerate_faces())
    surf.remove_unreferenced_vertices()
    h = float(size or default_mesh_size(surf))
    eps = 2.5e-3 if coarse else 1e-3
    with _LOCK:
        for _ in range(5):
            W = _load_ftetwild()
            if W is not None:
                p, t = _ftetwild(W, surf, h, eps, coarse)
            else:
                p, t = _gmsh(surf, h)
            if p is None:
                raise RuntimeError("No se pudo generar la malla de tetraedros de la pieza.")
            if p.shape[1] <= max_nodes:
                break
            h *= (p.shape[1] / max_nodes) ** (1 / 3) * 1.1
            eps = min(eps * 1.5, 5e-3)
    return _orient(p, t)


def _ftetwild(W, surf, h, eps, coarse):
    # fTetWild escribe un fichero de depuración en la carpeta actual: se borra al terminar
    debug_file = os.path.join(os.getcwd(), "__tracked_surface.stl")
    existed = os.path.exists(debug_file)
    try:
        return _ftetwild_call(W, surf, h, eps, coarse)
    finally:
        if not existed and os.path.exists(debug_file):
            try:
                os.remove(debug_file)
            except OSError:
                pass


def _ftetwild_call(W, surf, h, eps, coarse):
    v, t = W.tetrahedralize_mesh(
        np.ascontiguousarray(surf.vertices, dtype=np.float64),
        np.ascontiguousarray(surf.faces, dtype=np.uint32),
        True,  # optimize: mejora la calidad de los tetraedros
        False,  # skip_simplify
        0.05,  # edge_length_r (ignorado: se da la absoluta)
        h,  # edge_length_abs
        eps,  # envolvente: distancia máx. a la superficie original (relativa a la diagonal)
        10.0,  # stop_energy
        bool(coarse),  # coarsen
        0,  # hilos (0 = todos)
        80,  # iteraciones de optimización
        6, True,  # log, quiet
        False, False,  # vtk_ordering, disable_filtering
        np.empty((0, 3)), np.empty((0, 4), dtype=np.int32), np.empty(0),
    )
    if len(t) == 0:
        return None, None
    return np.asarray(v, float).T.copy(), np.asarray(t, np.int64).T.copy()


def _gmsh(surf, h):
    import gmsh

    fine = _resize_surface(surf, h)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "pieza.stl")
        fine.export(path)
        gmsh.initialize(["-noenv"], readConfigFiles=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("pieza")
            gmsh.merge(path)
            loop = gmsh.model.geo.addSurfaceLoop([s[1] for s in gmsh.model.getEntities(2)])
            gmsh.model.geo.addVolume([loop])
            gmsh.model.geo.synchronize()
            gmsh.option.setNumber("Mesh.MeshSizeMax", h)
            gmsh.option.setNumber("Mesh.Algorithm3D", 1)
            gmsh.option.setNumber("Mesh.Optimize", 1)
            gmsh.model.mesh.generate(3)
            tags, coords, _ = gmsh.model.mesh.getNodes()
            types, _e, nodes = gmsh.model.mesh.getElements(3)
            if 4 not in list(types):
                return None, None
            tets = np.asarray(nodes[list(types).index(4)], dtype=np.int64).reshape(-1, 4)
        except Exception:
            return None, None
        finally:
            gmsh.finalize()
    coords = np.asarray(coords).reshape(-1, 3)
    lookup = np.zeros(int(tags.max()) + 1, dtype=np.int64)
    lookup[np.asarray(tags, dtype=np.int64)] = np.arange(len(tags))
    t = lookup[tets]
    used = np.unique(t)
    remap = -np.ones(len(coords), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return coords[used].T.copy(), remap[t].T.copy()


def _resize_surface(surf: trimesh.Trimesh, h: float) -> trimesh.Trimesh:
    target = int(max(400, surf.area / (np.sqrt(3) / 4 * h * h)))
    out = surf
    if len(surf.faces) > 1.3 * target:
        try:
            out = surf.simplify_quadric_decimation(face_count=target)
            if not out.is_watertight:
                out = surf
        except Exception:
            out = surf
    return out.subdivide_to_size(max_edge=h, max_iter=12)


def _orient(p, t):
    a, b, c, d = (p[:, t[i]] for i in range(4))
    vol = np.einsum("ij,ij->j", np.cross((b - a).T, (c - a).T).T, d - a)
    keep = np.abs(vol) > 1e-14 * max(np.abs(vol).max(), 1e-300)
    t = t[:, keep]
    vol = vol[keep]
    neg = vol < 0
    t[1, neg], t[2, neg] = t[2, neg].copy(), t[1, neg].copy()
    return p, t
