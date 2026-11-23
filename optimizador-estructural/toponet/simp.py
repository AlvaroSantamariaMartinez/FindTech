"""Optimización topológica SIMP 3D (mínima flexibilidad con restricción de volumen).

    min_x   c(x) = F^T U(x)
    s.a.    K(x) U = F
            V(x) / V0 = volfrac
            0 <= x <= 1

* Interpolación SIMP:   E(x) = Emin + x^p (E0 - Emin)
* Filtro de densidad:   x_tilde = (H x) / (H 1)          (evita tableros de ajedrez)
* Proyección Heaviside: x_bar = H_beta(x_tilde)           (diseños casi 0/1)
* Actualización:        Criterios de Optimalidad (OC)

Es el "modelo base" clásico de la aplicación y también el generador de las
etiquetas (ground truth) del dataset con el que se entrena la red neuronal.
Teoría completa en `guia/03-optimizacion-topologica.md`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np
from scipy import ndimage

from .fem import HexMesh, simp_modulus
from .problem import Problem

ProgressFn = Callable[[float, str], None]


def _noop(_p: float, _m: str) -> None:
    pass


class DensityFilter:
    """Filtro de densidad lineal con núcleo cónico de radio `rmin` (en vóxeles),
    restringido al dominio (los vóxeles de fuera no "contaminan" la media)."""

    def __init__(self, domain: np.ndarray, rmin: float):
        self.mask = domain.astype(float)
        r = int(np.ceil(rmin)) - 1
        r = max(r, 0)
        g = np.arange(-r, r + 1)
        dx, dy, dz = np.meshgrid(g, g, g, indexing="ij")
        self.kernel = np.maximum(0.0, rmin - np.sqrt(dx**2 + dy**2 + dz**2))
        self.Hs = ndimage.convolve(self.mask, self.kernel, mode="constant")
        self.Hs[self.Hs == 0] = 1.0

    def forward(self, x: np.ndarray) -> np.ndarray:
        return ndimage.convolve(x * self.mask, self.kernel, mode="constant") / self.Hs * self.mask

    def backward(self, g: np.ndarray) -> np.ndarray:
        """Regla de la cadena: dJ/dx = H^T (dJ/dx_tilde / Hs)."""
        return ndimage.convolve(g / self.Hs * self.mask, self.kernel, mode="constant") * self.mask


def heaviside(x: np.ndarray, beta: float, eta: float = 0.5):
    """Proyección tanh suave y su derivada."""
    if beta <= 0:
        return x, np.ones_like(x)
    den = np.tanh(beta * eta) + np.tanh(beta * (1 - eta))
    xb = (np.tanh(beta * eta) + np.tanh(beta * (x - eta))) / den
    dxb = beta * (1 - np.tanh(beta * (x - eta)) ** 2) / den
    return xb, dxb


@dataclass
class SimpResult:
    density: np.ndarray  # densidades físicas (nx,ny,nz) en [0,1]
    compliance: float
    history: List[float] = field(default_factory=list)
    iterations: int = 0
    time_s: float = 0.0


def run_simp(
    problem: Problem,
    max_iter: int = 60,
    penal: float = 3.0,
    rmin: float = 1.5,
    move: float = 0.2,
    tol: float = 0.01,
    projection: bool = True,
    beta_max: float = 8.0,
    x0: Optional[np.ndarray] = None,
    progress: ProgressFn = _noop,
    Emin_ratio: float = 1e-6,
) -> SimpResult:
    t0 = time.time()
    dom = problem.domain
    passive = problem.passive_solid
    design = problem.design
    n_dom = int(dom.sum())
    n_des = int(design.sum())
    E0 = problem.material.E
    h = problem.pitch

    # Volumen objetivo de los elementos diseñables
    target = problem.volfrac * n_dom - passive.sum()
    target = float(np.clip(target, 0.02 * max(n_des, 1), n_des))

    mesh = HexMesh(dom, problem.material.nu, problem.fixed)
    filt = DensityFilter(dom, rmin)

    if x0 is None:
        x = np.where(design, target / max(n_des, 1), 0.0)
    else:
        x = np.where(design, np.clip(x0, 0.0, 1.0), 0.0)
    x = np.where(passive, 1.0, x)

    beta = 1.0 if projection else 0.0
    if projection and x0 is not None:
        beta = 2.0  # arranque en caliente: ya partimos de un diseño razonable
    history: List[float] = []
    u_prev = None

    def physical(xd):
        xt = filt.forward(xd)
        xb, dxb = heaviside(xt, beta)
        xb = np.where(passive, 1.0, xb) * dom
        return xt, xb, dxb

    it = 0
    c = np.inf
    for it in range(1, max_iter + 1):
        xt, xb, dxb = physical(x)
        rho = xb[mesh.el_tuple]
        E_el = simp_modulus(rho, E0, penal, Emin_ratio)
        res = mesh.solve(E_el, h, problem.forces, x0=u_prev)
        u_prev = res.u
        c = res.compliance
        history.append(c)

        # Sensibilidades respecto a la densidad física x_bar
        dc_b = -penal * (1 - Emin_ratio) * E0 * h * np.power(np.maximum(xb, 1e-9), penal - 1) * res.ce
        dc_b = np.where(design, dc_b, 0.0)
        dv_b = design.astype(float)
        # Cadena: x_bar <- x_tilde <- x
        dc = filt.backward(dc_b * dxb)
        dv = filt.backward(dv_b * dxb)
        dc = np.minimum(dc, -1e-12) * design  # en compliance todas las sensibilidades son <= 0
        dv = np.maximum(dv, 1e-12)

        # ---- Criterios de optimalidad con bisección en el multiplicador lambda
        l1, l2 = 1e-12, 1e12
        x_new = x
        # con proyección fuerte un mismo cambio en x mueve mucho x_bar: reducimos el paso
        mv = move / max(1.0, np.sqrt(beta)) if projection else move
        while (l2 - l1) / (l1 + l2) > 1e-4:
            lmid = np.sqrt(l1 * l2)
            Be = np.sqrt(-dc / (dv * lmid))
            x_new = np.clip(x * Be, np.maximum(0.0, x - mv), np.minimum(1.0, x + mv))
            x_new = np.where(design, x_new, x)
            vol = physical(x_new)[1][design].sum()
            if vol > target:
                l1 = lmid
            else:
                l2 = lmid
        change = float(np.abs(x_new - x)[design].max()) if n_des else 0.0
        x = x_new

        frac = it / max_iter
        progress(frac, f"SIMP it {it}/{max_iter}  c={c:.4g}  cambio={change:.3f}  beta={beta:g}")

        # Continuación de beta: endurece la proyección cuando converge
        if projection and (change < tol or it % 20 == 0) and beta < beta_max:
            beta = min(beta * 2, beta_max)
        elif change < tol and (not projection or beta >= beta_max):
            break

    _, xb, _ = physical(x)
    return SimpResult(density=xb, compliance=c, history=history, iterations=it, time_s=time.time() - t0)
