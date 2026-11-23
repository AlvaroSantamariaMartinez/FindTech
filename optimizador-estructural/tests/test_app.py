"""Tests de plugins, red neuronal y API web."""
import os
import sys
import time

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from toponet.plugins import OptimizerPlugin, Param, get_plugin, list_plugins, load_plugins  # noqa: E402


def test_plugins_discovered():
    ids = {p["id"] for p in list_plugins()}
    assert {"simp", "toponet", "beso_ejemplo"} <= ids  # incluido + red + plugin externo


def test_param_coercion():
    p = Param("n", "int", 5, min=1, max=10)
    assert p.coerce("12") == 10 and p.coerce(None) == 5
    b = Param("b", "bool", False)
    assert b.coerce("true") is True
    c = Param("c", "choice", "a", choices=["a", "b"])
    assert c.coerce("z") == "a"


def test_unet_shapes_and_volume_calibration():
    torch = pytest.importorskip("torch")
    from toponet.nn.infer import calibrate_volume
    from toponet.nn.model import TopoNetUNet3D, pad_to_multiple
    from tests.test_core import cantilever

    m = TopoNetUNet3D(9, 8, 3)
    x = torch.zeros(1, 9, 20, 6, 5)
    xp, (X, Y, Z) = pad_to_multiple(x, m.multiple)
    assert m(xp).shape[-3:] == (24, 8, 8)
    p = cantilever(20, 4, 4, volfrac=0.3)
    rho = calibrate_volume(np.random.default_rng(0).normal(size=p.shape), p)
    assert abs(rho.mean() - 0.3) < 1e-3


def test_dataset_sample_and_features():
    from toponet.nn.dataset import problem_from_sample, random_problem
    from toponet.nn.features import N_FEATURES, build_features, flip_features

    p = random_problem(np.random.default_rng(3), (16, 8, 8))
    f = build_features(p)
    assert f.shape == (N_FEATURES, 16, 8, 8)
    assert np.isfinite(f).all() and f[7].max() <= 1.0 + 1e-6
    # reflejar dos veces es la identidad y la fuerza cambia de signo
    g = flip_features(f, 0)
    assert np.allclose(g[3], -np.flip(f[3], 0))
    assert np.allclose(flip_features(g, 0), f)
    s = {"features": f, "fixed": p.fixed, "forces": p.forces, "passive": p.passive_solid, "volfrac": p.volfrac}
    q = problem_from_sample(s)
    assert (q.domain == p.domain).all()


def test_api_end_to_end():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from webui.server import app

    c = TestClient(app)
    info = c.post("/api/examples/viga_voladizo.stl").json()
    assert info["triangles"] > 0
    vox = c.post("/api/voxelize", json={"mesh_id": info["mesh_id"], "resolution": 16, "preview": False}).json()
    assert vox["elements"] > 0
    lo, hi = info["bounds"]
    body = {
        "mesh_id": info["mesh_id"], "resolution": 16, "volfrac": 0.4,
        "regions": [{"kind": "fixed", "shape": "face", "face": "xmin"},
                    {"kind": "load", "shape": "sphere", "center": [hi[0], 15, 0], "radius": 6, "force": [0, 0, -100]}],
        "models": [{"id": "simp", "params": {"max_iter": 25}}, {"id": "beso_ejemplo", "params": {"max_iter": 30}}],
    }
    jid = c.post("/api/jobs", json=body).json()["job_id"]
    for _ in range(600):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert j["status"] == "done", j
    for run in j["runs"].values():
        assert run["status"] == "done", run
        rid = run["result_id"]
        mesh = c.get(f"/api/results/{rid}/mesh", params={"threshold": 0.4}).json()
        assert not mesh["mesh"]["empty"]
        stl = c.get(f"/api/results/{rid}/stl")
        assert stl.status_code == 200 and len(stl.content) > 84
    assert j["reference"]["metrics"]["volume_fraction"] == 1.0
