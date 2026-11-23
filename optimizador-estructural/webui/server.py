"""TopoNet Studio: servidor web (FastAPI).

    python -m webui.server            (o:  uvicorn webui.server:app --port 8000)
    -> abre http://localhost:8000

Arquitectura:
  * El navegador (three.js) visualiza el STL, permite colocar apoyos y cargas
    con clics y lanza trabajos.
  * Cada trabajo construye el `Problem` (voxelización + regiones), evalúa la pieza
    maciza como referencia y ejecuta en PARALELO todos los modelos elegidos.
  * Cada resultado se valida con el MISMO análisis FEM (toponet.analysis) para
    que la comparación sea justa, y se convierte en malla para el visor.
"""
from __future__ import annotations

import base64
import io
import os
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from toponet.analysis import evaluate  # noqa: E402
from toponet.geometry import (density_to_mesh, load_mesh, sample_field_at_points,  # noqa: E402
                              voxelize)
from toponet.plugins import get_plugin, list_plugins, load_errors, load_plugins  # noqa: E402
from toponet.problem import MATERIALS, Material, Problem, Region, apply_regions  # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
EXAMPLES = os.path.join(ROOT, "examples")
MAX_ELEMENTS = int(os.environ.get("TOPONET_MAX_ELEMENTS", "250000"))

app = FastAPI(title="TopoNet Studio", version="1.0")

MESHES: Dict[str, dict] = {}
VOXEL_CACHE: Dict[tuple, tuple] = {}
JOBS: Dict[str, dict] = {}
RESULTS: Dict[str, dict] = {}
LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=int(os.environ.get("TOPONET_WORKERS", "4")))


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _b64(a: np.ndarray, dtype) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype=dtype).tobytes()).decode("ascii")


def _clean(v: Any) -> Any:
    """Convierte numpy/inf a tipos JSON."""
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return f if np.isfinite(f) else None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _mesh_info(mid: str) -> dict:
    m = MESHES[mid]["mesh"]
    lo, hi = m.bounds
    return {
        "mesh_id": mid,
        "name": MESHES[mid]["name"],
        "bounds": [lo.tolist(), hi.tolist()],
        "size_mm": (hi - lo).tolist(),
        "triangles": int(len(m.faces)),
        "volume_mm3": float(m.volume) if m.is_watertight else None,
        "watertight": bool(m.is_watertight),
    }


def _register_mesh(data: bytes, name: str) -> dict:
    ext = os.path.splitext(name)[1].lower().lstrip(".") or "stl"
    try:
        mesh = load_mesh(data, file_type=ext)
    except Exception as e:
        raise HTTPException(400, f"No se pudo leer la malla: {e}")
    if len(mesh.faces) == 0:
        raise HTTPException(400, "La malla está vacía")
    mid = uuid.uuid4().hex[:12]
    MESHES[mid] = {"mesh": mesh, "name": name, "stl": mesh.export(file_type="stl")}
    return _mesh_info(mid)


def _voxels(mid: str, resolution: int):
    key = (mid, int(resolution))
    if key not in VOXEL_CACHE:
        if mid not in MESHES:
            raise HTTPException(404, "malla no encontrada")
        VOXEL_CACHE[key] = voxelize(MESHES[mid]["mesh"], int(resolution))
    return VOXEL_CACHE[key]


def _mesh_payload(mesh, scalars: Dict[str, np.ndarray]) -> dict:
    if mesh is None or len(mesh.faces) == 0:
        return {"empty": True}
    out = {
        "empty": False,
        "positions": _b64(mesh.vertices, np.float32),
        "indices": _b64(mesh.faces, np.uint32),
        "n_vertices": int(len(mesh.vertices)),
        "n_faces": int(len(mesh.faces)),
        "scalars": {},
    }
    for k, v in scalars.items():
        out["scalars"][k] = {"data": _b64(v, np.float32), "min": float(np.min(v)), "max": float(np.max(v)),
                             "p99": float(np.percentile(v, 99))}
    return out


# ---------------------------------------------------------------------------
# Modelos de datos de la API
# ---------------------------------------------------------------------------

class RegionIn(BaseModel):
    kind: str
    shape: str = "sphere"
    center: List[float] = [0, 0, 0]
    radius: float = 5.0
    face: str = "xmin"
    dofs: List[bool] = [True, True, True]
    force: List[float] = [0, 0, -100]
    keep_solid: bool = True


class MaterialIn(BaseModel):
    name: str = "PLA"
    E: float = 3500.0
    nu: float = 0.35
    yield_strength: float = 50.0
    density: float = 1.24


class ModelRun(BaseModel):
    id: str
    params: Dict[str, Any] = Field(default_factory=dict)


class JobIn(BaseModel):
    mesh_id: str
    resolution: int = 40
    volfrac: float = 0.3
    material: MaterialIn = Field(default_factory=MaterialIn)
    regions: List[RegionIn]
    models: List[ModelRun]
    safety_target: float = 1.5


class VoxelIn(BaseModel):
    mesh_id: str
    resolution: int = 40
    preview: bool = True


# ---------------------------------------------------------------------------
# Rutas: catálogo
# ---------------------------------------------------------------------------

@app.get("/api/models")
def api_models():
    return {"models": list_plugins(), "errors": load_errors()}


@app.post("/api/models/reload")
def api_models_reload():
    load_plugins(force=True)
    return {"models": list_plugins(), "errors": load_errors()}


@app.get("/api/materials")
def api_materials():
    return {k: vars(m) for k, m in MATERIALS.items()}


@app.get("/api/examples")
def api_examples():
    if not os.path.isdir(EXAMPLES):
        return []
    return sorted(f for f in os.listdir(EXAMPLES) if f.lower().endswith(".stl"))


@app.post("/api/examples/{name}")
def api_load_example(name: str):
    path = os.path.join(EXAMPLES, os.path.basename(name))
    if not os.path.isfile(path):
        raise HTTPException(404, "ejemplo no encontrado")
    with open(path, "rb") as fh:
        return _register_mesh(fh.read(), os.path.basename(name))


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 200 * 1024 * 1024:
        raise HTTPException(413, "archivo demasiado grande (máx. 200 MB)")
    return _register_mesh(data, file.filename or "pieza.stl")


@app.get("/api/mesh/{mid}/stl")
def api_mesh_stl(mid: str):
    if mid not in MESHES:
        raise HTTPException(404, "malla no encontrada")
    return Response(MESHES[mid]["stl"], media_type="model/stl")


@app.get("/api/mesh/{mid}/vertices")
def api_mesh_vertices(mid: str):
    """Vértices (fusionados) de la malla: el visor los usa para asociar los campos
    calculados en el servidor (p. ej. tensión) a los triángulos del STL."""
    if mid not in MESHES:
        raise HTTPException(404, "malla no encontrada")
    return {"positions": _b64(MESHES[mid]["mesh"].vertices, np.float32)}


@app.post("/api/voxelize")
def api_voxelize(body: VoxelIn):
    t = time.time()
    dom, origin, pitch = _voxels(body.mesh_id, body.resolution)
    out = {
        "grid": list(dom.shape),
        "pitch_mm": pitch,
        "origin": origin.tolist(),
        "elements": int(dom.sum()),
        "approx_dofs": int(3 * dom.sum() * 1.3),
        "voxel_volume_mm3": float(dom.sum() * pitch**3),
        "too_big": bool(dom.sum() > MAX_ELEMENTS),
        "time_s": time.time() - t,
    }
    if body.preview:
        vm = density_to_mesh(dom.astype(float), origin, pitch, 0.5, smooth_iters=0)
        out["mesh"] = _mesh_payload(vm, {})
    return out


# ---------------------------------------------------------------------------
# Trabajos
# ---------------------------------------------------------------------------

def _build_problem(job: JobIn) -> Problem:
    dom, origin, pitch = _voxels(job.mesh_id, job.resolution)
    if dom.sum() > MAX_ELEMENTS:
        raise ValueError(f"Demasiados elementos ({dom.sum()}); baja la resolución (máx. {MAX_ELEMENTS}).")
    m = job.material
    mat = Material(m.name, m.E, m.nu, m.yield_strength, m.density)
    n = tuple(s + 1 for s in dom.shape)
    p = Problem(dom, np.zeros(n + (3,), bool), np.zeros(n + (3,)), material=mat,
                volfrac=float(np.clip(job.volfrac, 0.02, 1.0)), pitch=pitch, origin=origin,
                name=MESHES[job.mesh_id]["name"])
    regions = [Region.from_dict(r.model_dump()) for r in job.regions]
    if not any(r.kind == "fixed" for r in regions):
        raise ValueError("Añade al menos un apoyo (región fija).")
    if not any(r.kind == "load" for r in regions):
        raise ValueError("Añade al menos una carga.")
    return apply_regions(p, regions)


def _display_density(problem: Problem, density: np.ndarray, ev) -> np.ndarray:
    d = np.where(problem.passive_solid, 1.0, np.clip(density, 0, 1)) * problem.domain
    removed = (d >= 0.5) & ~ev.solid
    d[removed] = 0.0
    return d


def _make_result_mesh(rid: str, threshold: float) -> dict:
    r = RESULTS[rid]
    p: Problem = r["problem"]
    cache = r.setdefault("mesh_cache", {})
    key = round(float(threshold), 3)
    if key in cache:
        return cache[key]
    if abs(key - 0.5) < 1e-9:
        ev = r["evaluation"]
    else:
        ev = evaluate(p, r["density"], threshold=key, reference_compliance=r.get("ref_c"),
                      target_safety_factor=r.get("safety_target", 1.5))
    dens = _display_density(p, r["density"], ev)
    mesh = density_to_mesh(dens, p.origin, p.pitch, threshold=key, smooth_iters=8)
    scal = {}
    if mesh is not None and len(mesh.vertices):
        scal["von_mises"] = sample_field_at_points(ev.von_mises, p.origin, p.pitch, mesh.vertices)
        scal["displacement"] = sample_field_at_points(ev.displacement, p.origin, p.pitch, mesh.vertices)
        r.setdefault("stl_cache", {})[key] = mesh.export(file_type="stl")
    payload = {"threshold": key, "mesh": _mesh_payload(mesh, scal), "metrics": _clean(ev.metrics),
               "checks": _clean(ev.checks)}
    cache[key] = payload
    return payload


def _run_model(job_id: str, run_key: str, problem: Problem, model: ModelRun, ref_c: float, safety: float):
    job = JOBS[job_id]
    run = job["runs"][run_key]

    def progress(frac: float, msg: str):
        run["progress"] = float(np.clip(frac, 0, 1))
        run["message"] = msg

    try:
        plugin = get_plugin(model.id)
        ok, why = plugin.available()
        if not ok:
            raise RuntimeError(why)
        params = plugin.resolve_params(model.params)
        run["params"] = params
        run["status"] = "running"
        t0 = time.time()
        dens = plugin.optimize(problem, params, progress)
        dens = np.asarray(dens, dtype=float)
        if dens.shape != problem.shape:
            raise ValueError(f"el modelo devolvió forma {dens.shape}, se esperaba {problem.shape}")
        t_opt = time.time() - t0
        run["message"] = "Validando con FEM…"
        ev = evaluate(problem, dens, reference_compliance=ref_c, target_safety_factor=safety)
        ev.metrics["optimize_time_s"] = t_opt
        rid = uuid.uuid4().hex[:12]
        RESULTS[rid] = {"problem": problem, "density": dens, "evaluation": ev, "ref_c": ref_c,
                        "safety_target": safety, "name": run["name"], "mesh_name": problem.name}
        _make_result_mesh(rid, 0.5)
        run.update(status="done", progress=1.0, message=f"Listo en {t_opt:.1f} s", result_id=rid,
                   metrics=_clean(ev.metrics), checks=_clean(ev.checks))
    except Exception as e:  # el error de un modelo no tumba a los demás
        run.update(status="error", message=str(e), error=traceback.format_exc(limit=4))


def _run_job(job_id: str, body: JobIn):
    job = JOBS[job_id]
    try:
        job["message"] = "Voxelizando y aplicando condiciones de contorno…"
        problem = _build_problem(body)
        job["problem"] = _clean(problem.summary())
        job["message"] = "Analizando la pieza original (referencia)…"
        ref = evaluate(problem, np.ones(problem.shape), target_safety_factor=body.safety_target)
        ref_c = ref.metrics["compliance_Nmm"]
        rid = uuid.uuid4().hex[:12]
        RESULTS[rid] = {"problem": problem, "density": np.ones(problem.shape), "evaluation": ref, "ref_c": ref_c,
                        "safety_target": body.safety_target, "name": "Original", "mesh_name": problem.name}
        job["reference"] = {"result_id": rid, "metrics": _clean(ref.metrics), "checks": _clean(ref.checks)}
        # campo de tensiones de la pieza original sobre SU malla (para colorear el STL)
        om = MESHES[body.mesh_id]["mesh"]
        job["reference"]["vertex_von_mises"] = _b64(
            sample_field_at_points(ref.von_mises, problem.origin, problem.pitch, om.vertices), np.float32)
        job["status"] = "running"
        job["message"] = "Optimizando…"
        futs = []
        for key, m in zip(job["runs"].keys(), body.models):
            futs.append(EXECUTOR.submit(_run_model, job_id, key, problem, m, ref_c, body.safety_target))
        for f in futs:
            f.result()
        job["status"] = "done"
        job["message"] = "Terminado"
    except Exception as e:
        job["status"] = "error"
        job["message"] = str(e)
        job["error"] = traceback.format_exc(limit=4)
        for r in job["runs"].values():
            if r["status"] in ("queued", "running"):
                r.update(status="error", message="trabajo cancelado: " + str(e))
    job["finished"] = time.time()


@app.post("/api/jobs")
def api_create_job(body: JobIn):
    if body.mesh_id not in MESHES:
        raise HTTPException(404, "malla no encontrada; súbela de nuevo")
    if not body.models:
        raise HTTPException(400, "elige al menos un modelo")
    job_id = uuid.uuid4().hex[:12]
    runs = {}
    for i, m in enumerate(body.models):
        try:
            name = get_plugin(m.id).name
        except KeyError:
            raise HTTPException(400, f"modelo desconocido: {m.id}")
        runs[f"{i}:{m.id}"] = {"model_id": m.id, "name": name, "status": "queued", "progress": 0.0,
                               "message": "en cola"}
    JOBS[job_id] = {"id": job_id, "status": "preparing", "message": "", "runs": runs, "created": time.time(),
                    "mesh_id": body.mesh_id}
    threading.Thread(target=_run_job, args=(job_id, body), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "trabajo no encontrado")
    j = JOBS[job_id]
    return JSONResponse(_clean({k: v for k, v in j.items() if k != "error"} | {"error": j.get("error")}))


@app.get("/api/results/{rid}/mesh")
def api_result_mesh(rid: str, threshold: float = 0.5):
    if rid not in RESULTS:
        raise HTTPException(404, "resultado no encontrado")
    return JSONResponse(_make_result_mesh(rid, float(np.clip(threshold, 0.05, 0.95))))


@app.get("/api/results/{rid}/stl")
def api_result_stl(rid: str, threshold: float = 0.5):
    if rid not in RESULTS:
        raise HTTPException(404, "resultado no encontrado")
    key = round(float(np.clip(threshold, 0.05, 0.95)), 3)
    _make_result_mesh(rid, key)
    data = RESULTS[rid].get("stl_cache", {}).get(key)
    if data is None:
        raise HTTPException(400, "el diseño está vacío con ese umbral")
    r = RESULTS[rid]
    base = os.path.splitext(r["mesh_name"])[0]
    import unicodedata

    ascii_name = unicodedata.normalize("NFKD", r["name"]).encode("ascii", "ignore").decode()
    safe = "".join(c if c.isalnum() else "_" for c in ascii_name)[:40]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode() or "pieza"
    fname = f"{base}_{safe}_u{int(key*100)}.stl"
    return Response(data, media_type="model/stl", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/api/results/{rid}/density.npz")
def api_result_density(rid: str):
    if rid not in RESULTS:
        raise HTTPException(404, "resultado no encontrado")
    r = RESULTS[rid]
    p: Problem = r["problem"]
    buf = io.BytesIO()
    np.savez_compressed(buf, density=r["density"].astype(np.float32), domain=p.domain, origin=p.origin, pitch=p.pitch)
    return Response(buf.getvalue(), media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="densidad.npz"'})


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main():
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="TopoNet Studio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    load_plugins()
    print(f"TopoNet Studio en http://{a.host}:{a.port}")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
