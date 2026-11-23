"""Generación del dataset sintético y `Dataset` de PyTorch.

Cada muestra = (rasgos del problema, densidad óptima calculada con SIMP).

    python -m toponet.nn.generate_data --n 800 --out data/dataset --workers 4

Ver `guia/06-sistema-entrenamiento.md` (sección "Generar datos").
"""
from __future__ import annotations

import glob
import os
from typing import List, Optional, Tuple

import numpy as np

from ..geometry import largest_component
from ..problem import Material, Problem, Region, apply_regions
from ..simp import run_simp
from .features import build_features, flip_features, swap_yz_features

DEFAULT_SHAPE = (32, 16, 16)


# ---------------------------------------------------------------------------
# Dominios aleatorios
# ---------------------------------------------------------------------------

def random_domain(rng: np.random.Generator, shape=DEFAULT_SHAPE) -> np.ndarray:
    nx, ny, nz = shape
    I, J, K = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    kind = rng.choice(["box", "box", "L", "holes", "slot", "plate"])
    # sub-caja principal
    size = [max(4, int(s * rng.uniform(0.6, 1.0))) for s in shape]
    if kind == "plate":
        thin_ax = rng.integers(1, 3)
        size[thin_ax] = int(rng.integers(3, 7))
    lo = [int(rng.integers(0, s - sz + 1)) for s, sz in zip(shape, size)]
    dom = ((I >= lo[0]) & (I < lo[0] + size[0]) & (J >= lo[1]) & (J < lo[1] + size[1])
           & (K >= lo[2]) & (K < lo[2] + size[2]))
    if kind == "L":
        # quita una esquina
        cx = lo[0] + int(size[0] * rng.uniform(0.35, 0.7))
        cz = lo[2] + int(size[2] * rng.uniform(0.35, 0.7))
        if rng.random() < 0.5:
            dom &= ~((I >= cx) & (K >= cz))
        else:
            dom &= ~((I < cx) & (K >= cz))
    elif kind == "holes":
        for _ in range(int(rng.integers(1, 4))):
            ax = int(rng.integers(0, 3))
            c = [rng.uniform(lo[d] + 2, lo[d] + size[d] - 2) for d in range(3)]
            r = rng.uniform(1.5, max(2.0, min(size) / 3))
            coords = [I, J, K]
            dist2 = sum((coords[d] + 0.5 - c[d]) ** 2 for d in range(3) if d != ax)
            dom &= ~(dist2 < r * r)
    elif kind == "slot":
        ax = int(rng.integers(0, 3))
        other = [d for d in range(3) if d != ax]
        d0 = other[int(rng.integers(0, 2))]
        coords = [I, J, K]
        a = lo[d0] + int(size[d0] * rng.uniform(0.3, 0.5))
        b = a + max(2, int(size[d0] * rng.uniform(0.15, 0.3)))
        d1 = [d for d in other if d != d0][0]
        cut_from = lo[d1] + int(size[d1] * rng.uniform(0.3, 0.6))
        dom &= ~((coords[d0] >= a) & (coords[d0] < b) & (coords[d1] >= cut_from))
    return largest_component(dom)


def surface_nodes(problem: Problem) -> np.ndarray:
    """Nodos activos que tocan algún elemento vacío (están en la superficie)."""
    dom = problem.domain
    active = problem.active_nodes()
    nx, ny, nz = dom.shape
    padded = np.pad(dom, 1)
    interior = np.ones(active.shape, dtype=bool)
    for a in (0, 1):
        for b in (0, 1):
            for c in (0, 1):
                interior &= padded[a : a + nx + 1, b : b + ny + 1, c : c + nz + 1]
    return active & ~interior


def random_problem(rng: np.random.Generator, shape=DEFAULT_SHAPE, max_tries: int = 20) -> Problem:
    for _ in range(max_tries):
        dom = random_domain(rng, shape)
        if dom.sum() < 0.15 * np.prod(shape):
            continue
        n0 = tuple(s + 1 for s in shape)
        p = Problem(dom, np.zeros(n0 + (3,), bool), np.zeros(n0 + (3,)), material=Material(),
                    volfrac=float(rng.uniform(0.12, 0.45)), pitch=1.0)
        surf = surface_nodes(p)
        sidx = np.argwhere(surf)
        regions: List[Region] = []
        mode = rng.choice(["face", "face", "two_ends", "patches"])
        lo_b = np.argwhere(dom).min(0)
        hi_b = np.argwhere(dom).max(0) + 1
        diag = float(np.linalg.norm(hi_b - lo_b))
        if mode == "face":
            regions.append(Region("fixed", "face", face=str(rng.choice(["xmin", "xmax", "zmin"]))))
        elif mode == "two_ends":
            ax = 0
            up = int(rng.integers(1, 3))
            for end in (lo_b[ax], hi_b[ax]):
                c = np.zeros(3)
                c[ax] = end
                c[up] = lo_b[up]
                c[3 - ax - up] = (lo_b[3 - ax - up] + hi_b[3 - ax - up]) / 2
                roller = end == hi_b[ax] and rng.random() < 0.5
                dofs = [True, True, True]
                if roller:
                    dofs = [False, False, False]
                    dofs[up] = True
                    dofs[3 - ax - up] = True
                regions.append(Region("fixed", "sphere", center=tuple(c), radius=rng.uniform(1.5, 3.0), dofs=tuple(dofs)))
        else:
            for _k in range(int(rng.integers(2, 4))):
                c = sidx[rng.integers(len(sidx))].astype(float)
                regions.append(Region("fixed", "sphere", center=tuple(c), radius=rng.uniform(1.5, 3.0)))
        p = apply_regions(p, regions)
        fixed_nodes = np.argwhere(p.fixed.any(-1))
        if len(fixed_nodes) < 3:
            continue
        # cargas lejos de los apoyos
        dmin = np.min(np.linalg.norm(sidx[:, None, :] - fixed_nodes[None, ::max(1, len(fixed_nodes) // 200), :], axis=-1), axis=1)
        far = sidx[dmin > 0.35 * diag]
        if len(far) == 0:
            continue
        for _k in range(int(rng.integers(1, 3))):
            c = far[rng.integers(len(far))].astype(float)
            if rng.random() < 0.5:
                v = np.zeros(3)
                v[rng.integers(3)] = rng.choice([-1, 1])
            else:
                v = rng.normal(size=3)
                v /= np.linalg.norm(v)
            regions.append(Region("load", "sphere", center=tuple(c), radius=rng.uniform(1.0, 2.5),
                                  force=tuple(v * rng.uniform(0.5, 1.0))))
        p = apply_regions(p, regions)
        if np.abs(p.forces).sum() == 0:
            continue
        # el volumen pasivo no debe superar el objetivo
        if p.passive_solid.sum() > 0.8 * p.volfrac * p.n_domain:
            p.volfrac = min(0.6, 1.3 * p.passive_solid.sum() / p.n_domain)
        return p
    raise RuntimeError("no se pudo generar un problema válido")


def make_sample(seed: int, shape=DEFAULT_SHAPE, simp_iters: int = 60) -> dict:
    rng = np.random.default_rng(seed)
    p = random_problem(rng, shape)
    feats = build_features(p)
    res = run_simp(p, max_iter=simp_iters, projection=True)
    return {
        "features": feats.astype(np.float16),
        "target": res.density.astype(np.float16),
        "volfrac": np.float32(p.volfrac),
        "compliance": np.float64(res.compliance),
        "seed": np.int64(seed),
        "fixed": p.fixed,
        "forces": p.forces.astype(np.float32),
        "passive": p.passive_solid,
    }


def problem_from_sample(s: dict) -> Problem:
    """Reconstruye el `Problem` a partir de una muestra guardada (para validar con FEM)."""
    dom = np.asarray(s["features"][0]) > 0.5
    return Problem(dom, np.asarray(s["fixed"], bool), np.asarray(s["forces"], float),
                   passive_solid=np.asarray(s["passive"], bool), material=Material(),
                   volfrac=float(s["volfrac"]), pitch=1.0)


# ---------------------------------------------------------------------------
# Dataset de PyTorch
# ---------------------------------------------------------------------------

def list_samples(folder: str) -> List[str]:
    return sorted(glob.glob(os.path.join(folder, "*.npz")))


class TopologyDataset:
    """Carga todas las muestras en memoria (son pequeñas) y aplica aumentación.

    Aumentación por simetrías físicas: un espejo del problema produce el espejo
    de la solución. Con 3 espejos + intercambio y-z obtenemos hasta 16 variantes
    de cada muestra "gratis".
    """

    def __init__(self, files: List[str], augment: bool = False, seed: int = 0):
        import torch  # noqa: F401  (comprueba que PyTorch está disponible)

        self.augment = augment
        self.rng = np.random.default_rng(seed)
        X, Y = [], []
        for f in files:
            d = np.load(f)
            X.append(d["features"].astype(np.float32))
            Y.append(d["target"].astype(np.float32))
        self.X = np.stack(X)
        self.Y = np.stack(Y)
        self.files = files

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, i: int):
        import torch

        x, y = self.X[i], self.Y[i]
        if self.augment:
            for ax in range(3):
                if self.rng.random() < 0.5:
                    x = flip_features(x, ax)
                    y = np.flip(y, axis=ax)
            if x.shape[2] == x.shape[3] and self.rng.random() < 0.5:
                x = swap_yz_features(x)
                y = np.swapaxes(y, 1, 2)
        return torch.from_numpy(np.ascontiguousarray(x)), torch.from_numpy(np.ascontiguousarray(y))[None]


def split_files(files: List[str], val_fraction: float = 0.1, seed: int = 0) -> Tuple[List[str], List[str]]:
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(files))
    n_val = max(1, int(round(len(files) * val_fraction)))
    val = [files[i] for i in idx[:n_val]]
    train = [files[i] for i in idx[n_val:]]
    return train, val
