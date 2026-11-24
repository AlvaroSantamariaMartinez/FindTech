"""Análisis estructural avanzado ("física realista") sobre la geometría real.

A diferencia de la validación rápida por vóxeles (`toponet/analysis.py`), aquí la
pieza (el STL original o el optimizado y suavizado) se malla con tetraedros y se
analiza con elementos CUADRÁTICOS. Toda la física procede de proyectos
establecidos; este módulo solo los conecta:

| Física                               | Fuente                                                     |
|--------------------------------------|------------------------------------------------------------|
| Malla de tetraedros                  | gmsh (tutorial t13)                                        |
| Elasticidad lineal (P2)              | scikit-fem `skfem.models.elasticity`                       |
| Peso propio                          | scikit-fem (forma lineal de fuerza de volumen)             |
| Anisotropía de impresión FDM         | J. Bleyer, *Numerical Tours* (comet-fenicsx), tour de      |
|                                      | elasticidad ortótropa: S -> C = S⁻¹, extendido a 3D        |
| Pandeo lineal (rigidez geométrica)   | J. Bleyer, *Numerical Tours*, "Linear buckling analysis of |
|                                      | a 3D solid": K φ = λ K_G(σ₀) φ                             |
| Frecuencias naturales                | scikit-fem, ejemplo ex03 (K φ = ω² M φ)                    |
| Fatiga (Basquin + Goodman)           | fatpack (`LinearEnduranceCurve`,                           |
|                                      | `find_goodman_equivalent_stress`)                          |
| Delaminación entre capas             | criterio cuadrático de Brewer & Lagace (1988)              |

Las validaciones frente a soluciones analíticas están en `tests/test_physics.py` y
la teoría en `guia/11-fisica-realista.md`.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from ..problem import Material, Region

ProgressFn = Callable[[float, str], None]
G_MM_S2 = 9810.0  # gravedad [mm/s²]
DIRECT_LIMIT = 30000  # GDL libres hasta los que se factoriza (LU); por encima, multigrid (SuperLU escala mal en 3D)
EIGEN_MAX_DOFS = 80000  # pandeo y modos: si la malla estática es mayor, se usa otra de ~14 elementos


def _noop(_f, _m):
    pass


@dataclass
class AdvancedSettings:
    gravity: bool = True  # incluir el peso propio
    gravity_dir: tuple = (0.0, 0.0, -1.0)
    fdm: bool = False  # impresión 3D por capas: material transversalmente isótropo
    build_axis: str = "z"  # dirección de apilado de capas
    cycles: float = 0.0  # ciclos de carga requeridos (0 = no evaluar fatiga)
    load_ratio: float = 0.0  # R = σmin/σmax (0 = pulsante 0→máx, -1 = alterna)
    buckling: bool = True
    n_modes: int = 3  # frecuencias naturales a calcular (0 = ninguna)
    mesh_quality: str = "normal"  # "rápida" | "normal" | "fina"
    mesh_size: float = 0.0  # tamaño de elemento en mm (0 = según mesh_quality)
    exclusion: float = 1.5  # radio de exclusión alrededor de apoyos/cargas, en tamaños de elemento
    target_sf: float = 1.5  # factor de seguridad estático exigido
    target_buckling: float = 3.0  # factor de carga de pandeo exigido (imperfecciones)

    @staticmethod
    def from_dict(d: Optional[dict]) -> "AdvancedSettings":
        s = AdvancedSettings()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                cur = getattr(s, k)
                if isinstance(cur, bool):
                    v = bool(v)
                elif isinstance(cur, (int, float)) and not isinstance(cur, bool):
                    v = type(cur)(float(v))
                elif isinstance(cur, tuple):
                    v = tuple(float(x) for x in v)
                setattr(s, k, v)
        return s


@dataclass
class AdvancedResult:
    metrics: Dict[str, float]
    checks: List[dict]
    surface_vertices: np.ndarray  # (n, 3)
    surface_faces: np.ndarray  # (m, 3)
    surface_fields: Dict[str, np.ndarray] = field(default_factory=dict)  # por vértice
    settings: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Ley de comportamiento
# ---------------------------------------------------------------------------

AXES = {"x": 0, "y": 1, "z": 2}


def transversely_isotropic_C(mat: Material, axis: str = "z") -> np.ndarray:
    """Matriz de rigidez 6x6 (Voigt: xx, yy, zz, yz, xz, xy; cortantes de ingeniería)
    de un material transversalmente isótropo con eje de simetría `axis`.

    Como en el tour de elasticidad ortótropa de Bleyer: se escribe la matriz de
    FLEXIBILIDAD S con los módulos de ingeniería y se invierte numéricamente.
    Plano de capas isótropo (E_p = E, ν_p = ν); perpendicular E_z = r·E; se supone
    ν_pz = ν (=> ν_zp = ν·E_z/E_p por simetría) y G_z = E_z / (2(1+ν)).
    """
    Ep, nu = mat.E, mat.nu
    Ez = mat.E * mat.layer_E_ratio
    Gp = Ep / (2 * (1 + nu))
    Gz = Ez / (2 * (1 + nu))
    S = np.zeros((6, 6))
    S[0, 0] = S[1, 1] = 1 / Ep
    S[2, 2] = 1 / Ez
    S[0, 1] = S[1, 0] = -nu / Ep
    S[0, 2] = S[2, 0] = S[1, 2] = S[2, 1] = -nu / Ep  # = -ν_zp/E_z
    S[3, 3] = S[4, 4] = 1 / Gz  # yz, xz: cortante a través de las capas
    S[5, 5] = 1 / Gp  # xy: cortante en el plano de capa
    C_local = np.linalg.inv(S)
    a = AXES[axis]
    if a == 2:
        return C_local
    # rotación de ejes: el eje local 3 (z) pasa a ser el eje `axis`
    perm = {0: [1, 2, 0], 1: [2, 0, 1]}[a]  # local -> global
    R = np.zeros((3, 3))
    for loc, glob in enumerate(perm):
        R[glob, loc] = 1.0
    return _rotate_voigt_C(C_local, R)


def _voigt_pairs():
    return [(0, 0), (1, 1), (2, 2), (1, 2), (0, 2), (0, 1)]


def _rotate_voigt_C(C: np.ndarray, R: np.ndarray) -> np.ndarray:
    """Rota un tensor de rigidez en Voigt: C'_ijkl = R_ip R_jq R_kr R_ls C_pqrs."""
    C4 = np.zeros((3, 3, 3, 3))
    pairs = _voigt_pairs()
    for I, (i, j) in enumerate(pairs):
        for J, (k, l) in enumerate(pairs):
            for a, b in {(i, j), (j, i)}:
                for c, d in {(k, l), (l, k)}:
                    C4[a, b, c, d] = C[I, J]
    C4r = np.einsum("ip,jq,kr,ls,pqrs->ijkl", R, R, R, R, C4)
    out = np.zeros((6, 6))
    for I, (i, j) in enumerate(pairs):
        for J, (k, l) in enumerate(pairs):
            out[I, J] = C4r[i, j, k, l]
    return out


def make_stress_function(mat: Material, settings: AdvancedSettings):
    """Devuelve σ(ε) que opera sobre campos tensoriales de scikit-fem (3,3,...)."""
    if not settings.fdm:
        from skfem.models.elasticity import lame_parameters, linear_stress

        return linear_stress(*lame_parameters(mat.E, mat.nu))  # isótropo: directamente de scikit-fem
    C = transversely_isotropic_C(mat, settings.build_axis)
    pairs = _voigt_pairs()

    def sigma(T):
        eps = np.stack([T[i, j] * (1.0 if i == j else 2.0) for (i, j) in pairs])  # Voigt con γ = 2ε
        s = np.einsum("IJ,J...->I...", C, eps)
        out = np.empty_like(T)
        for I, (i, j) in enumerate(pairs):
            out[i, j] = s[I]
            out[j, i] = s[I]
        return out

    return sigma


# ---------------------------------------------------------------------------
# Fatiga (fatpack)
# ---------------------------------------------------------------------------

def fatigue_check(smax: float, load_ratio: float, material: Material, cycles: float):
    """Factor de seguridad a fatiga en el punto más solicitado.

    * La carga oscila entre R·σmax y σmax  -> rango Δσ = (1-R)σmax, media σm = (1+R)σmax/2.
    * Corrección de la tensión media de Goodman (fatpack): rango equivalente con media nula.
    * Curva S-N de Basquin (fatpack.LinearEnduranceCurve): S^m · N = cte, anclada en la
      resistencia a fatiga del material (amplitud Sf a N_ref ciclos, R = -1 -> rango 2·Sf).
    Devuelve (FS, vida en ciclos, rango equivalente).
    """
    import fatpack

    rng = np.array([smax * (1 - load_ratio)])
    mean = np.array([smax * (1 + load_ratio) / 2])
    eq_range = float(fatpack.find_goodman_equivalent_stress(rng, mean, material.ultimate_strength)[0])
    curve = fatpack.LinearEnduranceCurve(2 * material.fatigue_strength)
    curve.Nc = material.fatigue_cycles_ref
    curve.m = material.fatigue_exponent
    allowed = float(curve.get_stress(cycles))
    if eq_range <= 0:
        return float("inf"), float("inf"), 0.0
    return allowed / eq_range, float(curve.get_endurance(eq_range)), eq_range


def _val(x):
    """Valor numérico de un campo de scikit-fem (DiscreteField) o de un array."""
    return getattr(x, "value", x)


# ---------------------------------------------------------------------------
# Utilidades de solución
# ---------------------------------------------------------------------------

def _rigid_modes(doflocs: np.ndarray, dofs: np.ndarray) -> np.ndarray:
    """Modos rígidos para el multigrid en GDL vectoriales de scikit-fem (orden x,y,z intercalado)."""
    comp = dofs % 3
    x, y, z = doflocs[:, dofs]
    B = np.zeros((len(dofs), 6))
    for d in range(3):
        B[comp == d, d] = 1.0
    B[comp == 0, 3], B[comp == 1, 3] = -y[comp == 0], x[comp == 1]
    B[comp == 1, 4], B[comp == 2, 4] = -z[comp == 1], y[comp == 2]
    B[comp == 0, 5], B[comp == 2, 5] = z[comp == 0], -x[comp == 2]
    return B


class SPDSolver:
    """Resuelve K x = b para la K condensada: LU si es pequeña, AMG-CG si es grande.
    Se reutiliza en estática, pandeo y modos (los autovalores necesitan K⁻¹ muchas veces)."""

    def __init__(self, K: sp.spmatrix, doflocs: np.ndarray, free: np.ndarray):
        self.K = K.tocsr()
        self.n = K.shape[0]
        if self.n <= DIRECT_LIMIT:
            self.lu = spla.splu(K.tocsc(), permc_spec="MMD_AT_PLUS_A")
            self.ml = None
        else:
            import pyamg

            self.lu = None
            B = _rigid_modes(doflocs, free)
            self.ml = pyamg.smoothed_aggregation_solver(self.K, B=B, max_coarse=800, coarse_solver="splu")
        self.ok = True

    def solve(self, b: np.ndarray, rtol: float = 1e-10) -> np.ndarray:
        if self.lu is not None:
            return self.lu.solve(b)
        x, info = spla.cg(self.K, b, rtol=rtol, maxiter=2000, M=self.ml.aspreconditioner())
        if info != 0:
            self.ok = False
        return x

    def operator(self) -> spla.LinearOperator:
        return spla.LinearOperator((self.n, self.n), matvec=self.solve, dtype=float)

    def preconditioner(self):
        """Un ciclo V del multigrid: aproximación barata de K⁻¹ para LOBPCG."""
        if self.ml is None:
            return self.operator()
        return self.ml.aspreconditioner(cycle="V")


# ---------------------------------------------------------------------------
# Selección de apoyos y cargas sobre la malla de tetraedros
# ---------------------------------------------------------------------------

def _region_facets(mesh, region: Region, h: float, bbox) -> np.ndarray:
    bf = mesh.boundary_facets()
    mid = mesh.p[:, mesh.facets[:, bf]].mean(axis=1)
    if region.shape == "sphere":
        d = np.linalg.norm(mid - np.asarray(region.center, float)[:, None], axis=0)
        sel = bf[d <= region.radius]
        if len(sel) == 0:
            sel = bf[np.argsort(d)[:3]]
        return sel
    if region.shape == "face":
        a = AXES[region.face[0]]
        target = bbox[0][a] if region.face.endswith("min") else bbox[1][a]
        tol = max(0.35 * h, 1e-6 * float(np.linalg.norm(bbox[1] - bbox[0])))
        sel = bf[np.abs(mid[a] - target) <= tol]
        # solo las caras casi perpendiculares al eje (no las laterales que llegan al borde)
        if len(sel):
            n = _facet_normals(mesh, sel)
            sel = sel[np.abs(n[a]) > 0.7]
        return sel
    raise ValueError(region.shape)


def _facet_normals(mesh, facets: np.ndarray) -> np.ndarray:
    P = mesh.p[:, mesh.facets[:, facets]]  # (3, 3 vértices, n)
    n = np.cross((P[:, 1] - P[:, 0]).T, (P[:, 2] - P[:, 0]).T).T
    return n / np.maximum(np.linalg.norm(n, axis=0), 1e-30)


# ---------------------------------------------------------------------------
# Modelo de elementos finitos (se construye para la malla normal y para la gruesa)
# ---------------------------------------------------------------------------

class _FEModel:
    """Malla + base P2 + rigidez + apoyos + cargas (+ peso) + solución estática."""

    def __init__(self, p, t, regions: List[Region], material: Material, s: AdvancedSettings, bbox=None):
        from skfem import Basis, ElementTetP1, ElementTetP2, ElementVector, FacetBasis, LinearForm, MeshTet, asm

        self.mesh = mesh = MeshTet(p, t)
        edges = mesh.p[:, mesh.edges]
        self.h = float(np.linalg.norm(edges[:, 1] - edges[:, 0], axis=0).mean())
        if bbox is None:  # las regiones "cara" se refieren a la caja de la pieza ORIGINAL
            bbox = (mesh.p.min(axis=1), mesh.p.max(axis=1))
        bbox = (np.asarray(bbox[0], float), np.asarray(bbox[1], float))
        self.e = e = ElementVector(ElementTetP2())
        self.basis = basis = Basis(mesh, e, intorder=2)
        self.sigma_fn = make_stress_function(material, s)

        # rigidez: forma de scikit-fem si el material es isótropo
        if not s.fdm:
            from skfem.models.elasticity import lame_parameters, linear_elasticity

            self.K = asm(linear_elasticity(*lame_parameters(material.E, material.nu)), basis)
        else:
            from skfem import BilinearForm
            from skfem.helpers import ddot, sym_grad

            sigma_fn = self.sigma_fn

            @BilinearForm
            def stiffness(u, v, w):
                return ddot(sigma_fn(sym_grad(u)), sym_grad(v))

            self.K = asm(stiffness, basis)

        # apoyos y cargas de superficie
        fixed, self.exclusion_pts, self.patch_pts = [], [], []
        f = np.zeros(basis.N)
        applied = np.zeros(3)
        for r in regions:
            facets = _region_facets(mesh, r, self.h, bbox)
            if len(facets) == 0:
                raise ValueError(f"La región {r.kind} ({r.shape}) no toca la superficie de la pieza.")
            pts = mesh.p[:, np.unique(mesh.facets[:, facets])]
            self.exclusion_pts.append(pts)
            if r.shape == "sphere":  # parche pequeño: carga o apoyo concentrado
                self.patch_pts.append(pts)
            if r.kind == "fixed":
                dv = basis.get_dofs(facets=facets)
                fixed += [dv.all(f"u^{d + 1}") for d in range(3) if r.dofs[d]]
            else:
                fb = FacetBasis(mesh, e, facets=facets, intorder=3)
                traction = np.asarray(r.force, float) / float(fb.dx.sum())  # fuerza total / área

                @LinearForm
                def surface_load(v, w, tr=traction):
                    return np.einsum("i,i...->...", tr, _val(v))

                f += asm(surface_load, fb)
                applied += np.asarray(r.force, float)
        if not fixed:
            raise ValueError("No hay apoyos.")
        self.D = np.unique(np.concatenate(fixed))

        # peso propio (sistema mm-N-s-t: densidad en t/mm³)
        self.rho = material.density * 1e-9
        self.volume = float(Basis(mesh, ElementTetP1(), intorder=1).dx.sum())
        self.weight = self.volume * self.rho * G_MM_S2
        if s.gravity:
            gdir = np.asarray(s.gravity_dir, float)
            gdir = gdir / max(np.linalg.norm(gdir), 1e-12)
            gvec = gdir * self.rho * G_MM_S2

            @LinearForm
            def body_force(v, w):
                return np.einsum("i,i...->...", gvec, _val(v))

            f += asm(body_force, basis)
            applied += gdir * self.weight
        self.f = f
        self.applied = applied

        # estática
        self.free = np.setdiff1d(np.arange(basis.N), self.D)
        self.Kc = self.K[self.free][:, self.free]
        self.solver = SPDSolver(self.Kc, basis.doflocs, self.free)
        self.u = np.zeros(basis.N)
        self.u[self.free] = self.solver.solve(f[self.free])

    def gauss_stress(self):
        from skfem.helpers import sym_grad

        return self.sigma_fn(sym_grad(self.basis.interpolate(self.u)))

    def vertex_stress(self):
        """Con desplazamientos P2 la tensión es lineal en cada tetraedro: sus extremos están
        en los VÉRTICES, que es donde se evalúa (los puntos de Gauss, interiores, la
        subestimarían en la superficie, donde nacen las grietas)."""
        from skfem import Basis
        from skfem.helpers import sym_grad

        Xv = np.array([[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]])
        vb = Basis(self.mesh, self.e, quadrature=(Xv, np.full(4, 1.0 / 24.0)))
        return self.sigma_fn(sym_grad(vb.interpolate(self.u)))

    def exclusion_mask(self, factor: float, patches_only: bool = False) -> np.ndarray:
        """True en los tetraedros cuyo centro está a menos de `factor`·h de un apoyo o carga
        (`patches_only`: solo de los parches esféricos, no de las caras completas)."""
        from scipy.spatial import cKDTree

        pts = self.patch_pts if patches_only else self.exclusion_pts
        if not pts:
            return np.zeros(self.mesh.t.shape[1], dtype=bool)
        centroids = self.mesh.p[:, self.mesh.t].mean(axis=1)
        dist, _ = cKDTree(np.concatenate(pts, axis=1).T).query(centroids.T)
        excl = dist <= factor * self.h
        return excl if (~excl).any() else np.zeros_like(excl)

    def buckling_factor(self, exclusion: float = 1.5) -> float:
        """Pandeo lineal (Bleyer, Numerical Tours): K φ = λ K_G(σ₀) φ, con
        K_G(du, v) = -∫ σ₀ : (∇du)ᵀ∇v. Se resuelve K_G φ = μ K φ (μ = 1/λ), que solo
        necesita factorizar K: el λ>0 más pequeño corresponde al μ>0 más grande.

        La pretensión σ₀ se anula alrededor de los apoyos y cargas CONCENTRADOS (parches
        esféricos): con una carga idealizada sobre unas pocas caras aparecen "pandeos"
        locales bajo la carga que dependen de la malla y no son físicos. Las cargas y
        apoyos de cara completa (tracción uniforme) no se tocan. Ver
        guia/11-fisica-realista.md (estudio de convergencia).
        """
        from skfem import BilinearForm, asm

        @BilinearForm
        def geometric_stiffness(du, v, w):
            return -np.einsum("ij...,ki...,kj...->...", _val(w["sig0"]), du.grad, v.grad)

        sig0 = self.gauss_stress()
        if exclusion > 0:
            sig0 = sig0 * (~self.exclusion_mask(exclusion, patches_only=True))[None, None, :, None]
        KG = asm(geometric_stiffness, self.basis, sig0=sig0)[self.free][:, self.free]
        mu = None
        if self.solver.lu is not None:  # problema pequeño: Lanczos (ARPACK) con K factorizada
            try:
                mu, _ = spla.eigsh(KG, k=2, M=self.Kc, Minv=self.solver.operator(), which="LA", tol=1e-5,
                                   ncv=min(24, self.Kc.shape[0] - 1), maxiter=3000)
            except spla.ArpackNoConvergence as e:
                # típico sin compresión: no hay autovalores positivos que separar -> LOBPCG
                mu = e.eigenvalues if len(e.eigenvalues) else None
        if mu is None:  # problema grande: LOBPCG (Knyazev 2001) precondicionado con el multigrid de K
            X = np.random.default_rng(0).normal(size=(self.Kc.shape[0], 2))
            import warnings

            warnings.filterwarnings("ignore", message=".*not reaching the requested tolerance.*")
            mu, _ = spla.lobpcg(KG, X, B=self.Kc, M=self.solver.preconditioner(), largest=True, tol=1e-5,
                                maxiter=300)
        mu_max = float(mu.max())
        lam = 1.0 / mu_max if mu_max > 1e-12 else float("inf")
        return float("inf") if lam > 1e4 else lam  # λ enorme = solo compresiones locales despreciables

    def natural_frequencies(self, n: int) -> np.ndarray:
        """Como el ejemplo ex03 de scikit-fem: K φ = ω² M φ (desplazamiento inverso en σ = 0)."""
        from skfem import Basis, BilinearForm, asm

        rho = self.rho

        @BilinearForm
        def mass(u, v, w):
            return rho * np.einsum("i...,i...->...", _val(u), _val(v))

        M = asm(mass, Basis(self.mesh, self.e, intorder=4))[self.free][:, self.free]
        k = int(min(n, max(1, self.Kc.shape[0] - 2)))
        if self.solver.lu is not None:
            w2, _ = spla.eigsh(self.Kc, k=k, M=M, sigma=0.0, which="LM", OPinv=self.solver.operator(), tol=1e-7)
        else:  # LOBPCG: el error del autovalor va con el cuadrado del residuo -> tol 1e-4 sobra
            X = np.random.default_rng(1).normal(size=(self.Kc.shape[0], k + 1))
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                w2, _ = spla.lobpcg(self.Kc, X, B=M, M=self.solver.preconditioner(), largest=False, tol=1e-4,
                                    maxiter=200)
            w2 = np.sort(w2)[:k]
        return np.sqrt(np.clip(np.sort(w2), 0, None)) / (2 * np.pi)


# ---------------------------------------------------------------------------
# Análisis principal
# ---------------------------------------------------------------------------

QUALITY = {  # elementos a lo largo de la pieza, nodos máximos de la malla de tetraedros
    "rápida": (12.0, 2500), "rapida": (12.0, 2500),
    "normal": (16.0, 4000),
    "fina": (24.0, 9000),
}


def analyze(tri_mesh, regions: List[Region], material: Material, settings: Optional[AdvancedSettings] = None,
            progress: ProgressFn = _noop, bbox=None) -> AdvancedResult:
    """Análisis avanzado de una pieza (malla triangular cerrada, en mm).

    `bbox` = (mín, máx) de la pieza ORIGINAL, para que las regiones de tipo "cara" se
    sitúen igual al analizar un diseño optimizado (que puede no llegar a esa cara).
    """
    from .tetmesh import default_mesh_size, tetrahedralize

    s = settings or AdvancedSettings()
    t0 = time.time()
    metrics: Dict[str, float] = {}
    checks: List[dict] = []

    # ---------------- malla y estática
    progress(0.02, "Mallando la geometría real con tetraedros (fTetWild)…")
    n_across, max_nodes = QUALITY.get(s.mesh_quality, QUALITY["normal"])
    h = s.mesh_size if s.mesh_size > 0 else default_mesh_size(tri_mesh, n_across)
    p, t = tetrahedralize(tri_mesh, size=h, max_nodes=max_nodes)
    progress(0.15, f"Ensamblando y resolviendo la estática P2 ({3 * p.shape[1]:,}+ GDL)…")
    fe = _FEModel(p, t, regions, material, s, bbox)
    mesh = fe.mesh
    metrics.update(tet_elements=int(mesh.t.shape[1]), tet_nodes=int(mesh.p.shape[1]),
                   element_size_mm=fe.h, dofs=int(fe.basis.N), volume_mm3=fe.volume,
                   mass_g=fe.volume * material.density / 1000.0, weight_N=fe.weight)

    # comprobación de equilibrio: reacciones = cargas aplicadas (+ peso)
    reac = fe.K @ fe.u - fe.f
    R = np.array([reac[fe.D[fe.D % 3 == d]].sum() for d in range(3)])
    eq_err = float(np.linalg.norm(R + fe.applied) / max(np.linalg.norm(fe.applied), 1e-12))
    metrics["equilibrium_error"] = eq_err
    metrics["compliance_Nmm"] = float(fe.f @ fe.u)
    unode = fe.u[fe.basis.nodal_dofs].T
    metrics["max_displacement_mm"] = float(np.linalg.norm(unode, axis=1).max())

    sig_v = fe.vertex_stress()  # (3,3,nel,4)
    sx, sy, sz = sig_v[0, 0], sig_v[1, 1], sig_v[2, 2]
    txy, tyz, txz = sig_v[0, 1], sig_v[1, 2], sig_v[0, 2]
    vm = np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3 * (txy**2 + tyz**2 + txz**2))
    principal = np.linalg.eigvalsh(np.moveaxis(sig_v.reshape(3, 3, -1), -1, 0)).reshape(vm.shape + (3,))

    # zonas de aplicación de cargas/apoyos (principio de Saint-Venant): ahí la tensión de
    # un modelo con cargas y apoyos idealizados no es representativa
    keep = ~fe.exclusion_mask(s.exclusion)
    vm_el = vm.max(axis=1)
    metrics["max_von_mises_MPa"] = float(vm_el.max())
    metrics["max_von_mises_design_MPa"] = float(vm_el[keep].max())
    metrics["p99_von_mises_MPa"] = float(np.percentile(vm_el[keep], 99))
    metrics["max_principal_MPa"] = float(principal[..., 2].max(axis=1)[keep].max())
    sf = material.yield_strength / max(metrics["max_von_mises_design_MPa"], 1e-12)
    metrics["safety_factor"] = sf
    metrics["safety_factor_incl_contacts"] = material.yield_strength / max(metrics["max_von_mises_MPa"], 1e-12)
    checks.append({"name": "Equilibrio", "ok": eq_err < 1e-6,
                   "detail": f"reacciones = cargas aplicadas + peso (error relativo {eq_err:.1e})"})
    checks.append({"name": "Resistencia estática", "ok": sf >= s.target_sf,
                   "detail": (f"FS = {sf:.2f} (σy {material.yield_strength:g} MPa / σvm máx "
                              f"{metrics['max_von_mises_design_MPa']:.1f} MPa fuera de las zonas de apoyo y carga; "
                              f"incluyéndolas FS = {metrics['safety_factor_incl_contacts']:.2f})")})
    checks.append({"name": "Solución estática", "ok": bool(fe.solver.ok),
                   "detail": "convergida" if fe.solver.ok else "el solver iterativo no convergió (¿pieza mal apoyada?)"})

    # ---------------- capas de impresión (delaminación)
    if s.fdm:
        a = AXES[s.build_axis]
        o = [i for i in range(3) if i != a]
        snn = sig_v[a, a]
        tau = np.sqrt(sig_v[a, o[0]] ** 2 + sig_v[a, o[1]] ** 2)
        Sn = material.interlayer_strength_ratio * material.ultimate_strength
        Ss = Sn  # cortadura entre capas ≈ tracción entre capas (supuesto conservador habitual en FDM)
        idx = (np.maximum(snn, 0) / Sn) ** 2 + (tau / Ss) ** 2  # Brewer & Lagace (1988)
        fs_layers = 1.0 / np.sqrt(max(float(idx.max(axis=1)[keep].max()), 1e-30))
        metrics["interlayer_safety_factor"] = fs_layers
        metrics["interlayer_strength_MPa"] = Sn
        checks.append({"name": "Adhesión entre capas", "ok": fs_layers >= s.target_sf,
                       "detail": f"FS = {fs_layers:.2f} frente a delaminación (resistencia entre capas {Sn:.1f} MPa, capas ⟂ {s.build_axis})"})

    # ---------------- fatiga
    if s.cycles > 0:
        progress(0.45, "Evaluando fatiga (fatpack)…")
        Rr = float(np.clip(s.load_ratio, -1.0, 0.95))
        fs_fat, life, eq_range = fatigue_check(float(vm_el[keep].max()), Rr, material, s.cycles)
        metrics["fatigue_safety_factor"] = fs_fat
        metrics["fatigue_life_cycles"] = life
        metrics["fatigue_equiv_range_MPa"] = eq_range
        checks.append({"name": "Fatiga", "ok": fs_fat >= 1.0,
                       "detail": (f"FS = {fs_fat:.2f} para {s.cycles:.0e} ciclos con R = {Rr:g} "
                                  f"(vida estimada {life:.2e} ciclos; Basquin m = {material.fatigue_exponent:g} + Goodman)")})

    # ---------------- pandeo y modos (magnitudes globales: con P2 convergen con mallas moderadas)
    if s.buckling or s.n_modes > 0:
        if fe.basis.N <= EIGEN_MAX_DOFS:
            fe_c = fe
        else:
            progress(0.5, "Malla para pandeo y modos…")
            pc, tc = tetrahedralize(tri_mesh, size=default_mesh_size(tri_mesh, 14.0), max_nodes=4000)
            fe_c = _FEModel(pc, tc, regions, material, s, bbox)
        metrics["eigen_dofs"] = int(fe_c.basis.N)
        if s.buckling:
            progress(0.6, "Pandeo lineal (rigidez geométrica)…")
            try:
                lam = fe_c.buckling_factor(s.exclusion)
                metrics["buckling_load_factor"] = lam
                checks.append({"name": "Pandeo", "ok": lam >= s.target_buckling,
                               "detail": ("sin compresiones capaces de pandear" if lam == float("inf") else
                                          f"las cargas pueden multiplicarse ×{lam:.1f} antes de pandear "
                                          f"(objetivo ≥ {s.target_buckling:g} por imperfecciones)")})
            except Exception as ex:
                checks.append({"name": "Pandeo", "ok": False, "detail": f"no se pudo calcular: {ex}"})
        if s.n_modes > 0:
            progress(0.8, "Frecuencias naturales…")
            try:
                for i, fr in enumerate(fe_c.natural_frequencies(s.n_modes)):
                    metrics[f"freq_{i + 1}_Hz"] = float(fr)
            except Exception as ex:
                checks.append({"name": "Frecuencias", "ok": False, "detail": f"no se pudo calcular: {ex}"})

    # ---------------- superficie para el visor
    progress(0.95, "Preparando la visualización…")
    bf = mesh.boundary_facets()
    tri = mesh.facets[:, bf].T
    used = np.unique(tri)
    remap = -np.ones(mesh.p.shape[1], dtype=np.int64)
    remap[used] = np.arange(len(used))
    # von Mises nodal para colorear: media de los tetraedros que comparten cada vértice
    acc = np.zeros(mesh.p.shape[1])
    cnt = np.zeros(mesh.p.shape[1])
    np.add.at(acc, mesh.t.ravel(), vm.T.ravel())
    np.add.at(cnt, mesh.t.ravel(), 1.0)
    vm_nodal = acc / np.maximum(cnt, 1.0)
    import trimesh

    surf = trimesh.Trimesh(mesh.p[:, used].T, remap[tri], process=False)
    trimesh.repair.fix_normals(surf)
    fields = {"von_mises": vm_nodal[used], "displacement": np.linalg.norm(unode[used], axis=1)}
    metrics["analysis_time_s"] = time.time() - t0
    progress(1.0, "Análisis avanzado terminado")
    return AdvancedResult(metrics, checks, np.asarray(surf.vertices), np.asarray(surf.faces), fields, asdict(s))
