"""TopoNet Studio — punto de entrada único (también del ejecutable).

    TopoNetStudio                       abre la aplicación web en el navegador
    TopoNetStudio servir --port 8080    igual, con opciones (--host, --no-navegador)
    TopoNetStudio generar-datos --n 800 --workers 4
    TopoNetStudio entrenar --epochs 80
    TopoNetStudio evaluar --n 40 --refine 10
    TopoNetStudio autoprueba            comprueba que la física y el modelo funcionan

Los argumentos de `generar-datos`, `entrenar` y `evaluar` son los mismos que los de
`python -m toponet.nn.generate_data | train | evaluate` (usa --help en cada uno).
Las rutas relativas se resuelven desde la carpeta en la que ejecutas el programa;
en el ejecutable, los checkpoints que guardes en `checkpoints/` junto a él aparecen
automáticamente en la WebUI.
"""
from __future__ import annotations

import multiprocessing
import os
import sys

COMMANDS = ("servir", "generar-datos", "entrenar", "evaluar", "autoprueba")


def _serve(argv):
    import argparse
    import threading
    import webbrowser

    ap = argparse.ArgumentParser(prog="TopoNetStudio servir")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-navegador", action="store_true", help="no abrir el navegador")
    a = ap.parse_args(argv)
    import uvicorn

    from toponet.plugins import load_plugins
    from webui.server import app

    load_plugins()
    url = f"http://{'localhost' if a.host in ('0.0.0.0', '127.0.0.1') else a.host}:{a.port}"
    print(f"TopoNet Studio en {url}  (Ctrl+C para salir)", flush=True)
    if not a.no_navegador:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


def _selftest(_argv):
    """Pruebas rápidas de extremo a extremo (útil tras instalar o empaquetar)."""
    import time

    import numpy as np
    import trimesh

    ok = True

    def check(name, fn):
        nonlocal ok
        t = time.time()
        try:
            detail = fn()
            print(f"[OK]    {name}: {detail} ({time.time() - t:.1f} s)", flush=True)
        except Exception as e:  # pragma: no cover
            ok = False
            print(f"[FALLO] {name}: {type(e).__name__}: {e}", flush=True)

    def fem_beam():
        from toponet.fem import HexMesh
        nx, ny, nz, L = 40, 8, 8, 100.0
        dom = np.ones((nx, ny, nz), bool)
        fixed = np.zeros((nx + 1, ny + 1, nz + 1, 3), bool)
        fixed[0] = True
        F = np.zeros((nx + 1, ny + 1, nz + 1, 3))
        F[-1, :, :, 2] = -100 / ((ny + 1) * (nz + 1))
        mesh = HexMesh(dom, 0.3, fixed)
        r = mesh.solve(np.full(mesh.n_elements, 1000.0), L / nx, F)
        w = -r.u[-1, :, :, 2].mean()
        assert abs(w / 2.5 - 1) < 0.02, w
        return f"flecha {w:.3f} mm (Euler-Bernoulli 2.500)"

    def simp():
        from toponet.problem import Problem
        from toponet.simp import run_simp
        nx, ny, nz = 16, 6, 3
        fixed = np.zeros((nx + 1, ny + 1, nz + 1, 3), bool)
        fixed[0] = True
        F = np.zeros((nx + 1, ny + 1, nz + 1, 3))
        F[-1, 0, :, 1] = -1
        r = run_simp(Problem(np.ones((nx, ny, nz), bool), fixed, F, volfrac=0.4), max_iter=20)
        return f"volumen {r.density.mean():.2f} (objetivo 0.40)"

    def meshing():
        from toponet.physics.tetmesh import available_meshers, tetrahedralize
        meshers = available_meshers()
        assert "fTetWild" in meshers, f"fTetWild no se pudo cargar (disponibles: {meshers})"
        p, t = tetrahedralize(trimesh.creation.box(extents=(100, 10, 10)), size=10)
        return f"{t.shape[1]} tetraedros con {meshers}"

    def buckling():
        from toponet.physics.advanced import AdvancedSettings, _FEModel
        from toponet.physics.tetmesh import tetrahedralize
        from toponet.problem import Material, Region
        mat = Material("t", 1000.0, 0.3, 100.0, 1.0)
        L, b = 200.0, 10.0
        p, t = tetrahedralize(trimesh.creation.box(extents=(b, b, L)), size=L / 14)
        regs = [Region("fixed", "face", face="zmin"), Region("load", "face", face="zmax", force=(0, 0, -1.0))]
        lam = _FEModel(p, t, regs, mat, AdvancedSettings(gravity=False)).buckling_factor()
        euler = np.pi**2 * 1000 * b**4 / 12 / (4 * L**2)
        assert abs(lam / euler - 1) < 0.05, lam
        return f"λ {lam:.2f} (Euler {euler:.2f})"

    def fatigue():
        from toponet.physics.advanced import fatigue_check
        from toponet.problem import MATERIALS
        fs, _life, _ = fatigue_check(18.0, -1.0, MATERIALS["PLA"], 1e6)
        assert abs(fs - 1) < 1e-9
        return "Basquin + Goodman (fatpack)"

    def network():
        from toponet.nn.infer import predict_density
        from toponet.nn.model import load_checkpoint
        from toponet.plugins.neural_unet import _checkpoint_paths
        from toponet.problem import Problem
        paths = _checkpoint_paths()
        if not paths:
            return "sin checkpoints (entrena uno con 'entrenar')"
        name, path = next(iter(sorted(paths.items())))
        model, _ = load_checkpoint(path)
        nx, ny, nz = 16, 8, 8
        fixed = np.zeros((nx + 1, ny + 1, nz + 1, 3), bool)
        fixed[0] = True
        F = np.zeros((nx + 1, ny + 1, nz + 1, 3))
        F[-1, :, :, 2] = -1
        rho = predict_density(model, Problem(np.ones((nx, ny, nz), bool), fixed, F, volfrac=0.3))
        return f"{name}: volumen {rho.mean():.2f} (objetivo 0.30)"

    def webapp():
        from fastapi.testclient import TestClient

        from webui.server import app
        c = TestClient(app)
        assert c.get("/").status_code == 200
        assert c.get("/static/vendor/three/three.module.js").status_code == 200
        r = c.get("/api/models").json()
        ids = sorted(m["id"] for m in r["models"])
        assert "simp" in ids and "toponet" in ids, (ids, r["errors"])
        assert not r["errors"], r["errors"]
        return f"modelos {ids}; web y three.js locales servidos"

    for name, fn in (("FEM (viga en voladizo)", fem_beam), ("Optimizador SIMP", simp), ("Mallado de tetraedros", meshing),
                     ("Pandeo (columna de Euler)", buckling), ("Fatiga", fatigue), ("Red neuronal", network),
                     ("Aplicación web", webapp)):
        check(name, fn)
    print("AUTOPRUEBA:", "CORRECTA" if ok else "CON FALLOS", flush=True)
    return 0 if ok else 1


def _utf8_console():
    """La consola de Windows usa cp1252 por defecto: sin esto, imprimir "λ" o "σ" falla."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None):
    multiprocessing.freeze_support()  # necesario para generar datos en paralelo desde el ejecutable
    _utf8_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv.pop(0) if argv and argv[0] in COMMANDS else "servir"
    if cmd == "servir":
        return _serve(argv)
    if cmd == "autoprueba":
        return _selftest(argv)
    if cmd == "generar-datos":
        from toponet.nn.generate_data import main as run
    elif cmd == "entrenar":
        from toponet.nn.train import main as run
    else:
        from toponet.nn.evaluate import main as run
    return run(argv)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    sys.exit(main() or 0)
