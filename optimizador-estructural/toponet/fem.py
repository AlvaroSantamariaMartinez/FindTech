"""Elementos finitos 3D con hexaedros lineales de 8 nodos (H8) sobre una rejilla de vóxeles.

Este módulo es el "juez" físico de todo el proyecto: lo usan el optimizador SIMP,
la generación del dataset, el cálculo de rasgos físicos para la red neuronal y
la validación final de cualquier diseño (venga del modelo que venga).

Las matrices de elemento proceden de scikit-fem (https://github.com/kinnala/scikit-fem);
este módulo solo añade un ensamblaje cacheado y solvers rápidos para la rejilla de vóxeles.

Ver `guia/03-elementos-finitos.md` para la teoría.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

try:  # multigrid algebraico: acelera muchísimo los sistemas grandes
    import pyamg

    HAS_PYAMG = True
except Exception:  # pragma: no cover
    HAS_PYAMG = False

# Coordenadas naturales (xi, eta, zeta) de los 8 nodos del hexaedro, en el mismo
# orden que los desplazamientos (a, b, c) de la rejilla.
NODE_SIGNS = np.array(
    [
        [-1, -1, -1],
        [1, -1, -1],
        [1, 1, -1],
        [-1, 1, -1],
        [-1, -1, 1],
        [1, -1, 1],
        [1, 1, 1],
        [-1, 1, 1],
    ],
    dtype=float,
)
NODE_OFFSETS = ((NODE_SIGNS + 1) // 2).astype(int)  # (0/1, 0/1, 0/1)

DIRECT_SOLVER_LIMIT = 3000  # nº de GDL libres por debajo del cual usamos solver directo


def constitutive_matrix(E: float = 1.0, nu: float = 0.3) -> np.ndarray:
    """Matriz D (6x6) de elasticidad lineal isótropa (notación de Voigt, cortantes de
    ingeniería), construida a partir de los parámetros de Lamé de scikit-fem."""
    from skfem.models.elasticity import lame_parameters

    lam, mu = lame_parameters(E, nu)
    D = np.zeros((6, 6))
    D[:3, :3] = lam
    D[0, 0] = D[1, 1] = D[2, 2] = lam + 2 * mu
    D[3, 3] = D[4, 4] = D[5, 5] = mu
    return D


def strain_displacement(xi: float, eta: float, zeta: float, h: float = 1.0) -> np.ndarray:
    """Matriz B (6x24) del H8 de lado h evaluada en (xi, eta, zeta)."""
    s = NODE_SIGNS
    dN = np.zeros((8, 3))  # dN_i/d(xi, eta, zeta)
    dN[:, 0] = s[:, 0] * (1 + s[:, 1] * eta) * (1 + s[:, 2] * zeta) / 8
    dN[:, 1] = s[:, 1] * (1 + s[:, 0] * xi) * (1 + s[:, 2] * zeta) / 8
    dN[:, 2] = s[:, 2] * (1 + s[:, 0] * xi) * (1 + s[:, 1] * eta) / 8
    dN *= 2.0 / h  # jacobiano de un cubo de lado h: dxi/dx = 2/h
    B = np.zeros((6, 24))
    for n in range(8):
        dx, dy, dz = dN[n]
        c = 3 * n
        B[0, c] = dx
        B[1, c + 1] = dy
        B[2, c + 2] = dz
        B[3, c], B[3, c + 1] = dy, dx  # gamma_xy
        B[4, c + 1], B[4, c + 2] = dz, dy  # gamma_yz
        B[5, c], B[5, c + 2] = dz, dx  # gamma_zx
    return B


@lru_cache(maxsize=16)
def element_stiffness(nu: float = 0.3) -> np.ndarray:
    """K_e (24x24) de un cubo de lado 1 y E = 1, ensamblada con **scikit-fem**.

    La física sale de la librería: forma débil `skfem.models.elasticity.linear_elasticity`
    con elementos trilineales `ElementHex1` e integración de Gauss exacta. Solo se
    reordenan los nodos al orden de `NODE_OFFSETS` que usa nuestro ensamblador rápido.
    (`tests/test_physics.py` comprueba que coincide con la K global de scikit-fem.)

    Para un vóxel de lado h y módulo E basta con escalar: K = E * h * K_e
    (B escala como 1/h y el volumen como h³ -> h³/h² = h).
    """
    from skfem import Basis, ElementHex1, ElementVector, MeshHex, asm
    from skfem.models.elasticity import lame_parameters, linear_elasticity

    m = MeshHex()  # cubo unidad con un único elemento
    basis = Basis(m, ElementVector(ElementHex1()), intorder=3)
    K = asm(linear_elasticity(*lame_parameters(1.0, nu)), basis).toarray()
    perm = [int(np.where((m.p.T == off).all(1))[0][0]) for off in NODE_OFFSETS]
    dofs = np.array([basis.nodal_dofs[:, n] for n in perm]).ravel()
    return K[np.ix_(dofs, dofs)]


def rigid_body_modes_dofs(dofs: np.ndarray, nn_shape) -> np.ndarray:
    """6 modos de sólido rígido evaluados en una lista de GDL (para el multigrid).

    Las 3 traslaciones y 3 rotaciones infinitesimales son el "núcleo" de K sin
    apoyos; dárselas al multigrid de agregación suavizada lo hace robusto en elasticidad.
    """
    comp = dofs % 3
    x, y, z = (c.astype(float) for c in np.unravel_index(dofs // 3, nn_shape))
    B = np.zeros((len(dofs), 6))
    for d in range(3):
        B[comp == d, d] = 1.0
    B[comp == 0, 3] = -y[comp == 0]  # rotación alrededor de z: (-y, x, 0)
    B[comp == 1, 3] = x[comp == 1]
    B[comp == 1, 4] = -z[comp == 1]  # rotación alrededor de x: (0, -z, y)
    B[comp == 2, 4] = y[comp == 2]
    B[comp == 0, 5] = z[comp == 0]  # rotación alrededor de y: (z, 0, -x)
    B[comp == 2, 5] = -x[comp == 2]
    return B


@dataclass
class FEResult:
    u: np.ndarray  # desplazamientos nodales (nx+1,ny+1,nz+1,3) [mm]
    compliance: float  # F·u [N·mm]  (= 2 x energía de deformación)
    ce: np.ndarray  # u_e^T K_e u_e por elemento, con K_e de E=1, h=1  (nx,ny,nz)
    converged: bool
    iterations: int


class HexMesh:
    """Malla de hexaedros sobre los elementos ACTIVOS de una rejilla, con apoyos fijos.

    * Solo se ensamblan los elementos con `active=True`; los nodos que no tocan
      ningún elemento activo se eliminan del sistema. Así un STL que ocupa un 30 %
      de su caja envolvente solo cuesta ese 30 %.
    * El patrón disperso de K (qué entradas son no nulas) se calcula UNA vez; en
      cada iteración de optimización solo cambian los valores -> ensamblaje rápido.
    * El precondicionador multigrid se reutiliza entre iteraciones (las densidades
      cambian poco de una iteración a la siguiente) y se reconstruye periódicamente.
    """

    def __init__(self, active: np.ndarray, nu: float, fixed: np.ndarray, rebuild_every: int = 1):
        self.active = np.asarray(active, dtype=bool)
        self.shape = self.active.shape
        nx, ny, nz = self.shape
        self.nn_shape = (nx + 1, ny + 1, nz + 1)
        self.nu = float(nu)
        self.KE = element_stiffness(round(self.nu, 6))
        self.el_idx = np.argwhere(self.active)  # (ne, 3)
        self.el_tuple = tuple(self.el_idx.T)
        ne = len(self.el_idx)
        node_ids = np.zeros((ne, 8), dtype=np.int64)
        for n, (a, b, c) in enumerate(NODE_OFFSETS):
            i = self.el_idx[:, 0] + a
            j = self.el_idx[:, 1] + b
            k = self.el_idx[:, 2] + c
            node_ids[:, n] = (i * (ny + 1) + j) * (nz + 1) + k
        self.node_ids = node_ids
        self.edof = np.repeat(node_ids * 3, 3, axis=1) + np.tile(np.arange(3), 8)[None, :]
        self.ndof = 3 * int(np.prod(self.nn_shape))

        used = np.zeros(self.ndof, dtype=bool)
        used[self.edof.ravel()] = True
        self.fixed = np.asarray(fixed, dtype=bool).reshape(-1)
        free = used & ~self.fixed
        self.free_idx = np.flatnonzero(free)
        self.n_free = len(self.free_idx)

        # ---- patrón disperso sobre los GDL libres (se calcula una sola vez)
        dof2free = -np.ones(self.ndof, dtype=np.int64)
        dof2free[self.free_idx] = np.arange(self.n_free)
        fe = dof2free[self.edof]  # (ne, 24)
        rows = np.repeat(fe, 24, axis=1).ravel()
        cols = np.tile(fe, (1, 24)).ravel()
        keep = (rows >= 0) & (cols >= 0)
        self._keep = keep
        keys = rows[keep] * self.n_free + cols[keep]
        uniq, inv = np.unique(keys, return_inverse=True)
        self._inv = inv
        self._nnz = len(uniq)
        r, c = np.divmod(uniq, self.n_free)
        indptr = np.zeros(self.n_free + 1, dtype=np.int64)
        np.add.at(indptr, r + 1, 1)
        self._indptr = np.cumsum(indptr)
        self._indices = c
        self._ke_flat = self.KE.ravel()
        self._ml = None
        self._solves = 0
        self.rebuild_every = rebuild_every

    @property
    def n_elements(self) -> int:
        return len(self.el_idx)

    # -------------------------------------------------------------- ensamblaje
    def assemble_free(self, E_el: np.ndarray, h: float) -> sp.csr_matrix:
        """K restringida a GDL libres. `E_el` = módulo de cada elemento activo (ne,)."""
        sK = (self._ke_flat[None, :] * (E_el * h)[:, None]).ravel()[self._keep]
        data = np.bincount(self._inv, weights=sK, minlength=self._nnz)
        return sp.csr_matrix((data, self._indices, self._indptr), shape=(self.n_free, self.n_free))

    # ------------------------------------------------------------- resolución
    def solve(
        self,
        E_el: np.ndarray,
        h: float,
        forces: np.ndarray,
        x0: Optional[np.ndarray] = None,
        rtol: float = 1e-7,
        maxiter: int = 3000,
        method: str = "auto",
    ) -> FEResult:
        f = np.asarray(forces, float).reshape(-1)
        ff = f[self.free_idx]
        u = np.zeros(self.ndof)
        converged, iters = True, 0
        if np.any(ff) and self.n_free > 0:
            K = self.assemble_free(E_el, h)
            if method == "auto":
                method = "direct" if (self.n_free < DIRECT_SOLVER_LIMIT or not HAS_PYAMG) else "amg"
            if method == "direct":
                uf = spla.spsolve(K.tocsc(), ff, permc_spec="MMD_AT_PLUS_A")
                if not np.all(np.isfinite(uf)):
                    converged = False
                    uf = np.nan_to_num(uf)
            else:
                if self._ml is None or self._solves % self.rebuild_every == 0:
                    B = rigid_body_modes_dofs(self.free_idx, self.nn_shape)
                    self._ml = pyamg.smoothed_aggregation_solver(K, B=B, max_coarse=500, coarse_solver="splu")
                M = self._ml.aspreconditioner(cycle="V")
                x0f = None if x0 is None else np.asarray(x0).reshape(-1)[self.free_idx]
                count = [0]

                def cb(_):
                    count[0] += 1

                uf, info = spla.cg(K, ff, x0=x0f, rtol=rtol, maxiter=maxiter, M=M, callback=cb)
                iters = count[0]
                converged = info == 0
                if not converged:  # precondicionador obsoleto: reconstruir y reintentar
                    B = rigid_body_modes_dofs(self.free_idx, self.nn_shape)
                    self._ml = pyamg.smoothed_aggregation_solver(K, B=B, max_coarse=500, coarse_solver="splu")
                    uf, info = spla.cg(K, ff, x0=uf, rtol=rtol, maxiter=maxiter,
                                       M=self._ml.aspreconditioner(cycle="V"))
                    converged = info == 0
            self._solves += 1
            u[self.free_idx] = uf
        compliance = float(f @ u)
        ue = u[self.edof]
        ce_act = np.einsum("ij,jk,ik->i", ue, self.KE, ue)
        ce = np.zeros(self.shape)
        ce[self.el_tuple] = ce_act
        return FEResult(u.reshape(self.nn_shape + (3,)), compliance, ce, converged, iters)

    # --------------------------------------------------------------- tensiones
    def element_stress(self, u: np.ndarray, E_el: np.ndarray, h: float) -> np.ndarray:
        """Tensor de tensiones (Voigt, 6 componentes) en el centro de cada elemento activo."""
        B0 = strain_displacement(0.0, 0.0, 0.0, h)
        D = constitutive_matrix(1.0, self.nu)
        ue = u.reshape(-1)[self.edof]
        eps = ue @ B0.T  # (ne, 6)
        return (eps @ D.T) * E_el[:, None]

    def von_mises(self, u: np.ndarray, E_el: np.ndarray, h: float) -> np.ndarray:
        """Tensión equivalente de von Mises por elemento (rejilla completa, 0 fuera)."""
        s = self.element_stress(u, E_el, h)
        sx, sy, sz, txy, tyz, tzx = s.T
        vm_act = np.sqrt(
            0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3 * (txy**2 + tyz**2 + tzx**2)
        )
        vm = np.zeros(self.shape)
        vm[self.el_tuple] = vm_act
        return vm


def simp_modulus(rho: np.ndarray, E0: float, penal: float = 3.0, Emin_ratio: float = 1e-6) -> np.ndarray:
    """Interpolación SIMP: E(rho) = Emin + rho^p (E0 - Emin)."""
    return E0 * (Emin_ratio + (1.0 - Emin_ratio) * np.power(rho, penal))
