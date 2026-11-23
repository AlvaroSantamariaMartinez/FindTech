"""Tests del núcleo: FEM, SIMP, geometría y validación.  python -m pytest -q"""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from toponet.analysis import evaluate, thin_voxels  # noqa: E402
from toponet.fem import HexMesh, element_stiffness  # noqa: E402
from toponet.geometry import density_to_mesh, voxelize  # noqa: E402
from toponet.problem import Material, Problem, Region, apply_regions  # noqa: E402
from toponet.simp import run_simp  # noqa: E402


def cantilever(nx=20, ny=4, nz=4, L=100.0, E=1000.0, P=100.0, volfrac=0.4):
    h = L / nx
    dom = np.ones((nx, ny, nz), bool)
    n = (nx + 1, ny + 1, nz + 1)
    fixed = np.zeros(n + (3,), bool)
    fixed[0] = True
    F = np.zeros(n + (3,))
    F[-1, :, :, 2] = -P / ((ny + 1) * (nz + 1))
    return Problem(dom, fixed, F, material=Material("t", E, 0.3, 50.0, 1.0), volfrac=volfrac, pitch=h)


def test_element_stiffness_rigid_modes():
    KE = element_stiffness(0.3)
    assert np.allclose(KE, KE.T)
    ev = np.sort(np.linalg.eigvalsh(KE))
    assert np.all(np.abs(ev[:6]) < 1e-10)  # 6 modos de sólido rígido
    assert ev[6] > 1e-3


@pytest.mark.parametrize("method", ["direct", "amg"])
def test_cantilever_matches_beam_theory(method):
    p = cantilever(40, 8, 8)
    mesh = HexMesh(p.domain, 0.3, p.fixed)
    res = mesh.solve(np.full(mesh.n_elements, p.material.E), p.pitch, p.forces, method=method)
    b = 8 * p.pitch
    I = b**4 / 12
    w_eb = 100 * 100.0**3 / (3 * 1000 * I)
    w = -res.u[-1, :, :, 2].mean()
    assert res.converged
    assert abs(w / w_eb - 1) < 0.02  # Euler-Bernoulli (+ pequeña contribución del cortante)
    assert np.isclose(res.compliance, (p.forces * res.u).sum())


def test_simp_respects_volume_and_improves():
    p = cantilever(24, 8, 4, volfrac=0.35)
    r = run_simp(p, max_iter=100)
    assert abs(r.density.mean() - 0.35) < 0.02
    assert r.history[-1] < r.history[0]  # mejora respecto al diseño uniforme inicial
    gray = ((r.density > 0.1) & (r.density < 0.9)).mean()
    assert gray < 0.15


def test_evaluate_detects_broken_load_path_and_islands():
    p = cantilever(20, 4, 4)
    solid = np.ones(p.shape)
    ev = evaluate(p, solid)
    assert all(c["ok"] for c in ev.checks if c["name"] in ("Camino de carga", "Sin islas flotantes"))
    cut = solid.copy()
    cut[10] = 0  # corta la viga por la mitad
    ev2 = evaluate(p, cut)
    names = {c["name"]: c["ok"] for c in ev2.checks}
    assert not names["Camino de carga"]
    assert not names["Sin islas flotantes"]
    assert ev2.metrics["removed_island_voxels"] == 9 * 16
    # un diseño que no transmite la carga nunca debe parecer "más rígido"
    assert ev2.metrics["compliance_Nmm"] == float("inf")
    assert ev2.metrics["safety_factor"] == 0.0


def test_thin_voxels():
    s = np.zeros((5, 5, 5), bool)
    s[2, :, :] = True  # lámina de 1 vóxel
    assert thin_voxels(s).sum() == 25
    s[1:4, :, :] = True  # 3 vóxeles de grosor
    assert thin_voxels(s).sum() == 0


def test_voxelize_box_volume():
    import trimesh

    m = trimesh.creation.box(extents=(40, 20, 10))
    dom, origin, pitch = voxelize(m, 40)
    assert dom.shape == (40, 20, 10)
    assert abs(dom.sum() * pitch**3 / m.volume - 1) < 0.01
    mesh = density_to_mesh(dom.astype(float), origin, pitch, smooth_iters=0)
    assert mesh.is_watertight


def test_regions():
    import trimesh

    m = trimesh.creation.box(extents=(40, 20, 10))
    dom, origin, pitch = voxelize(m, 20)
    n = tuple(s + 1 for s in dom.shape)
    p = Problem(dom, np.zeros(n + (3,), bool), np.zeros(n + (3,)), pitch=pitch, origin=origin)
    p = apply_regions(p, [Region("fixed", "face", face="xmin"),
                          Region("load", "sphere", center=(20, 0, 0), radius=3, force=(0, 0, -50))])
    assert p.fixed[0].all()
    assert np.isclose(p.forces[..., 2].sum(), -50)
    assert p.passive_solid.any()


def test_evaluate_empty_design_does_not_crash():
    p = cantilever(12, 3, 3)
    ref = evaluate(p, np.ones(p.shape)).metrics["compliance_Nmm"]
    ev = evaluate(p, np.full(p.shape, 0.4), reference_compliance=ref)  # todo gris < umbral
    assert ev.metrics["load_carried_pct"] < 99.9
    assert ev.metrics["stiffness_retained_pct"] == 0.0
