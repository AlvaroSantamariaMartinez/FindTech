"""Validación de la física "realista" frente a soluciones analíticas clásicas.

Cada test compara el análisis avanzado (fTetWild/gmsh + scikit-fem P2 + fatpack)
con una fórmula de libro. Si alguno falla, los resultados de la app no son fiables.
"""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

trimesh = pytest.importorskip("trimesh")
pytest.importorskip("skfem")

from toponet.physics.advanced import (AdvancedSettings, _FEModel, analyze, fatigue_check,  # noqa: E402
                                      transversely_isotropic_C)
from toponet.physics.tetmesh import tetrahedralize  # noqa: E402
from toponet.problem import Material, Region  # noqa: E402

MAT = Material("ensayo", E=1000.0, nu=0.3, yield_strength=100.0, density=1.0, ultimate_strength=120.0,
               fatigue_strength=40.0, fatigue_cycles_ref=1e6, fatigue_exponent=10.0,
               layer_E_ratio=0.8, interlayer_strength_ratio=0.5)
QUIET = AdvancedSettings(gravity=False, buckling=False, n_modes=0)


def _cantilever(L=200.0, b=20.0, n=14, force=(0, 0, -100), settings=QUIET):
    m = trimesh.creation.box(extents=(L, b, b))
    regs = [Region("fixed", "face", face="xmin"), Region("load", "face", face="xmax", force=force)]
    p, t = tetrahedralize(m, size=L / n, max_nodes=6000)
    return _FEModel(p, t, regs, MAT, settings)


def test_hex_element_matches_scikit_fem_global_matrix():
    """El FEM rápido de vóxeles del optimizador produce la MISMA K global que scikit-fem."""
    from skfem import Basis, ElementHex1, ElementVector, MeshHex, asm
    from skfem.models.elasticity import lame_parameters, linear_elasticity

    from toponet.fem import HexMesh

    nx, ny, nz = 3, 2, 2
    dom = np.ones((nx, ny, nz), bool)
    hm = HexMesh(dom, 0.3, np.zeros((nx + 1, ny + 1, nz + 1, 3), bool))
    K_ours = hm.assemble_free(np.ones(hm.n_elements), 1.0).toarray()
    ms = MeshHex.init_tensor(np.arange(nx + 1.0), np.arange(ny + 1.0), np.arange(nz + 1.0))
    b = Basis(ms, ElementVector(ElementHex1()), intorder=3)
    K_skfem = asm(linear_elasticity(*lame_parameters(1.0, 0.3)), b).toarray()
    # reordenar los GDL de scikit-fem al orden (i, j, k, componente) de nuestra rejilla
    idx = np.round(ms.p.T).astype(int)
    node_ours = (idx[:, 0] * (ny + 1) + idx[:, 1]) * (nz + 1) + idx[:, 2]
    perm = np.zeros(b.N, dtype=int)
    for n_s, n_o in enumerate(node_ours):
        perm[3 * n_o:3 * n_o + 3] = b.nodal_dofs[:, n_s]
    assert np.abs(K_ours - K_skfem[np.ix_(perm, perm)]).max() < 1e-12


def test_cantilever_deflection_and_stress_vs_beam_theory():
    L, b, P = 200.0, 20.0, 100.0
    fe = _cantilever(L, b)
    I = b**4 / 12
    w = np.abs(fe.u[fe.basis.nodal_dofs][2]).max()
    assert abs(w / (P * L**3 / (3 * MAT.E * I)) - 1) < 0.02  # Euler-Bernoulli (+ cortante)
    assert np.allclose(fe.f @ fe.u, P * w, rtol=0.03)


def test_equilibrium_with_gravity():
    s = AdvancedSettings(gravity=True, buckling=False, n_modes=0)
    fe = _cantilever(settings=s)
    reac = fe.K @ fe.u - fe.f
    R = np.array([reac[fe.D[fe.D % 3 == d]].sum() for d in range(3)])
    weight = 200 * 20 * 20 * MAT.density * 1e-9 * 9810.0
    # fTetWild reproduce la superficie dentro de una envolvente de 1e-3 x diagonal
    assert np.isclose(fe.weight, weight, rtol=2e-3)
    assert np.allclose(R, -fe.applied, atol=1e-6 * np.abs(fe.applied).max())  # equilibrio exacto
    assert np.isclose(fe.applied[2], -100.0 - fe.weight)


def test_euler_buckling_column():
    L, b = 200.0, 10.0
    m = trimesh.creation.box(extents=(b, b, L))
    regs = [Region("fixed", "face", face="zmin"), Region("load", "face", face="zmax", force=(0, 0, -1.0))]
    p, t = tetrahedralize(m, size=L / 16, max_nodes=6000)
    lam = _FEModel(p, t, regs, MAT, QUIET).buckling_factor()
    p_cr = np.pi**2 * MAT.E * (b**4 / 12) / (4 * L**2)  # columna empotrada-libre
    assert abs(lam / p_cr - 1) < 0.03


def test_tension_does_not_buckle():
    m = trimesh.creation.box(extents=(10, 10, 200))
    regs = [Region("fixed", "face", face="zmin"), Region("load", "face", face="zmax", force=(0, 0, 1.0))]
    p, t = tetrahedralize(m, size=200 / 16, max_nodes=6000)
    assert _FEModel(p, t, regs, MAT, QUIET).buckling_factor() == float("inf")


def test_cantilever_first_natural_frequency():
    L, b = 200.0, 20.0
    fe = _cantilever(L, b)
    f1 = fe.natural_frequencies(1)[0]
    rho = MAT.density * 1e-9
    f_an = 1.8751**2 / (2 * np.pi) * np.sqrt(MAT.E * b**4 / 12 / (rho * b * b * L**4))
    assert abs(f1 / f_an - 1) < 0.03


def test_transversely_isotropic_material():
    for axis, a in (("z", 2), ("x", 0), ("y", 1)):
        S = np.linalg.inv(transversely_isotropic_C(MAT, axis))
        for d in range(3):
            E_d = 1.0 / S[d, d]
            expected = MAT.E * MAT.layer_E_ratio if d == a else MAT.E
            assert np.isclose(E_d, expected, rtol=1e-10)
        assert np.allclose(S, S.T)


def test_fatigue_basquin_goodman():
    # a la amplitud de referencia, completamente alternada (R=-1) y N_ref ciclos: FS = 1
    fs, life, _ = fatigue_check(MAT.fatigue_strength, -1.0, MAT, MAT.fatigue_cycles_ref)
    assert np.isclose(fs, 1.0) and np.isclose(life, MAT.fatigue_cycles_ref)
    # Basquin: 10x ciclos -> tensión admisible / 10^(1/m)
    fs10, _, _ = fatigue_check(MAT.fatigue_strength, -1.0, MAT, 10 * MAT.fatigue_cycles_ref)
    assert np.isclose(fs10, 10 ** (-1 / MAT.fatigue_exponent))
    # Goodman: una tensión media de tracción empeora la fatiga
    fs_pulsating, _, _ = fatigue_check(2 * MAT.fatigue_strength, 0.0, MAT, MAT.fatigue_cycles_ref)
    assert fs_pulsating < 1.0


def test_full_analysis_runs_on_example():
    from toponet.geometry import load_mesh

    m = load_mesh(os.path.join(ROOT, "examples", "viga_voladizo.stl"))
    regs = [Region("fixed", "face", face="xmin"),
            Region("load", "sphere", center=(120, 15, 0), radius=6, force=(0, 0, -200))]
    s = AdvancedSettings(fdm=True, cycles=1e5, mesh_quality="rápida", n_modes=2)
    r = analyze(m, regs, MAT, s)
    names = {c["name"] for c in r.checks}
    assert {"Equilibrio", "Resistencia estática", "Adhesión entre capas", "Fatiga", "Pandeo"} <= names
    assert r.metrics["equilibrium_error"] < 1e-6
    assert len(r.surface_faces) > 0 and len(r.surface_fields["von_mises"]) == len(r.surface_vertices)
