"""Geometría: STL <-> rejilla de vóxeles.

* `load_mesh`        lee y repara un STL (u OBJ/PLY) con trimesh.
* `voxelize`         convierte la malla en un dominio de diseño booleano.
* `density_to_mesh`  convierte un campo de densidades en una malla triangular
                     (marching cubes + suavizado de Taubin) lista para exportar a STL.

Teoría en `guia/04-stl-y-voxelizacion.md`.
"""
from __future__ import annotations

import io
from typing import Optional, Tuple, Union

import numpy as np
import trimesh
from scipy import ndimage


def load_mesh(src: Union[str, bytes, io.BytesIO], file_type: str = "stl") -> trimesh.Trimesh:
    """Carga una malla y aplica reparaciones básicas."""
    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(src)
    if isinstance(src, io.BytesIO):
        mesh = trimesh.load(src, file_type=file_type, force="mesh")
    else:
        mesh = trimesh.load(src, force="mesh")
    if isinstance(mesh, trimesh.Scene):  # pragma: no cover
        mesh = mesh.dump(concatenate=True)
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    if not mesh.is_watertight:
        mesh.fill_holes()
    trimesh.repair.fix_normals(mesh)
    return mesh


def grid_for_mesh(mesh: trimesh.Trimesh, resolution: int, padding: int = 0):
    """Calcula origen, tamaño de vóxel (pitch) y forma de la rejilla.

    `resolution` = nº de vóxeles a lo largo del eje MÁS LARGO de la pieza.
    """
    lo, hi = mesh.bounds
    ext = hi - lo
    pitch = float(ext.max() / resolution)
    shape = np.maximum(1, np.ceil(ext / pitch - 1e-9).astype(int)) + 2 * padding
    center = (lo + hi) / 2
    origin = center - pitch * shape / 2
    return origin, pitch, tuple(int(s) for s in shape)


def _parity_fill(tris: np.ndarray, origin: np.ndarray, pitch: float, shape, axis: int) -> np.ndarray:
    """Relleno por paridad de rayos paralelos al eje `axis`, que pasan por los
    centros de los vóxeles. Un punto está dentro si el rayo que llega a él ha
    cruzado un número impar de triángulos.

    Totalmente vectorizado: para cada triángulo se enumeran las columnas de la
    rejilla que caen dentro de su proyección (caja envolvente) y se hace el test
    baricéntrico en 2D.
    """
    a, b = [d for d in range(3) if d != axis]
    na, nb, nc = shape[a], shape[b], shape[axis]
    # pequeño desplazamiento irracional para no pasar exactamente por aristas/vértices
    jitter = np.array([1.234567e-4, 2.345678e-4, 3.456789e-4]) * pitch
    P = (tris - origin - jitter) / pitch - 0.5  # coordenadas en "índices de centro"
    pa, pb, pc = P[:, :, a], P[:, :, b], P[:, :, axis]
    ia0 = np.clip(np.ceil(pa.min(1)), 0, na).astype(np.int64)
    ia1 = np.clip(np.floor(pa.max(1)), -1, na - 1).astype(np.int64)
    ib0 = np.clip(np.ceil(pb.min(1)), 0, nb).astype(np.int64)
    ib1 = np.clip(np.floor(pb.max(1)), -1, nb - 1).astype(np.int64)
    cna = np.maximum(ia1 - ia0 + 1, 0)
    cnb = np.maximum(ib1 - ib0 + 1, 0)
    counts = np.zeros((na, nb, nc + 1), dtype=np.int32)
    total = cna * cnb
    valid = np.flatnonzero(total > 0)
    chunk = 2_000_000
    start = 0
    # procesa en bloques para acotar memoria
    cum = np.cumsum(total[valid])
    while start < len(valid):
        base = cum[start - 1] if start > 0 else 0
        end = int(np.searchsorted(cum, base + chunk, side="right"))
        end = max(end, start + 1)
        sel = valid[start:end]
        reps = total[sel]
        t = np.repeat(sel, reps)
        local = np.arange(reps.sum()) - np.repeat(np.cumsum(reps) - reps, reps)
        ii = ia0[t] + local // cnb[t]
        jj = ib0[t] + local % cnb[t]
        x0, y0 = pa[t, 0], pb[t, 0]
        x1, y1 = pa[t, 1], pb[t, 1]
        x2, y2 = pa[t, 2], pb[t, 2]
        det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        ok = np.abs(det) > 1e-14
        det = np.where(ok, det, 1.0)
        l0 = ((y1 - y2) * (ii - x2) + (x2 - x1) * (jj - y2)) / det
        l1 = ((y2 - y0) * (ii - x2) + (x0 - x2) * (jj - y2)) / det
        l2 = 1 - l0 - l1
        inside = ok & (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        zc = l0 * pc[t, 0] + l1 * pc[t, 1] + l2 * pc[t, 2]
        kk = np.clip(np.ceil(zc), 0, nc).astype(np.int64)  # primer centro por encima del cruce
        np.add.at(counts, (ii[inside], jj[inside], kk[inside]), 1)
        start = end
    filled = (np.cumsum(counts, axis=2)[:, :, :nc] % 2) == 1
    # reordenar ejes (a, b, axis) -> (x, y, z)
    order = np.argsort([a, b, axis])
    return np.transpose(filled, order)


def voxelize(mesh: trimesh.Trimesh, resolution: int = 40) -> Tuple[np.ndarray, np.ndarray, float]:
    """Devuelve (domain, origin, pitch).

    Se hace el relleno por paridad en los 3 ejes y se vota por mayoría, lo que
    hace el resultado robusto frente a mallas con pequeños defectos.
    """
    origin, pitch, shape = grid_for_mesh(mesh, resolution)
    tris = np.asarray(mesh.triangles, dtype=float)
    votes = sum(_parity_fill(tris, origin, pitch, shape, ax).astype(np.int8) for ax in range(3))
    domain = votes >= 2
    if not domain.any():
        # Malla no cerrada (o muy fina): usamos la superficie engordada
        vg = mesh.voxelized(pitch).fill()
        pts = vg.points
        idx = np.floor((pts - origin) / pitch).astype(int)
        idx = idx[np.all((idx >= 0) & (idx < np.array(shape)), axis=1)]
        domain = np.zeros(shape, dtype=bool)
        domain[tuple(idx.T)] = True
    return domain, origin, pitch


def largest_component(mask: np.ndarray) -> np.ndarray:
    """Se queda con la mayor componente conexa (conectividad por caras)."""
    lab, n = ndimage.label(mask)
    if n <= 1:
        return mask
    sizes = ndimage.sum(mask, lab, index=np.arange(1, n + 1))
    return lab == (1 + int(np.argmax(sizes)))


def density_to_mesh(
    density: np.ndarray,
    origin: np.ndarray,
    pitch: float,
    threshold: float = 0.5,
    smooth_iters: int = 10,
) -> Optional[trimesh.Trimesh]:
    """Isosuperficie `density == threshold` -> malla triangular cerrada."""
    from skimage import measure

    d = np.pad(np.asarray(density, float), 1, mode="constant", constant_values=0.0)
    if d.max() < threshold:
        return None
    level = float(np.clip(threshold, d.min() + 1e-6, d.max() - 1e-6))
    verts, faces, _normals, _ = measure.marching_cubes(d, level=level)
    # índice (con padding) -> coordenadas: el valor del elemento i vive en su centro
    verts = np.asarray(origin) + pitch * (verts - 1 + 0.5)
    mesh = trimesh.Trimesh(vertices=verts, faces=faces[:, ::-1], process=True)
    if smooth_iters > 0 and len(mesh.faces) > 0:
        trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53, iterations=smooth_iters)
    trimesh.repair.fix_normals(mesh)
    return mesh


def mesh_to_stl_bytes(mesh: trimesh.Trimesh) -> bytes:
    return mesh.export(file_type="stl")


def sample_field_at_points(field: np.ndarray, origin: np.ndarray, pitch: float, pts: np.ndarray) -> np.ndarray:
    """Valor del campo por elemento (p. ej. von Mises) en puntos arbitrarios (vecino
    más cercano entre los elementos con valor > 0)."""
    idx = np.floor((pts - origin) / pitch).astype(int)
    idx = np.clip(idx, 0, np.array(field.shape) - 1)
    vals = field[tuple(idx.T)]
    # si cae en un vóxel vacío (bordes del marching cubes), usa el máximo de sus vecinos
    if np.any(vals == 0):
        fmax = ndimage.maximum_filter(field, size=3)
        vals = np.where(vals == 0, fmax[tuple(idx.T)], vals)
    return vals
