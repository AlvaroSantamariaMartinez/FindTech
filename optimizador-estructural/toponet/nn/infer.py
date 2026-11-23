"""Inferencia: del `Problem` a un campo de densidades que respeta el volumen pedido."""
from __future__ import annotations

import numpy as np
import torch

from ..problem import Problem
from .features import build_features
from .model import TopoNetUNet3D, pad_to_multiple


def calibrate_volume(logits: np.ndarray, problem: Problem, iters: int = 60) -> np.ndarray:
    """Busca (bisección) un sesgo b tal que mean(sigmoid(logits + b)) sobre el dominio
    sea exactamente la fracción de volumen pedida.

    La red aprende la *forma*; esta corrección garantiza la *cantidad* de material,
    que es una restricción dura del problema.
    """
    dom = problem.domain
    passive = problem.passive_solid
    design = problem.design
    target = problem.volfrac * dom.sum() - passive.sum()
    target = float(np.clip(target, 0.0, design.sum()))
    z = logits[design]
    lo, hi = -30.0, 30.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        v = (1 / (1 + np.exp(-(z + mid)))).sum()
        if v > target:
            hi = mid
        else:
            lo = mid
    rho = 1 / (1 + np.exp(-(logits + 0.5 * (lo + hi))))
    rho = np.where(design, rho, 0.0)
    rho = np.where(passive, 1.0, rho)
    return rho


@torch.no_grad()
def predict_logits(model: TopoNetUNet3D, feats: np.ndarray, device: str = "cpu") -> np.ndarray:
    x = torch.from_numpy(feats[None]).float().to(device)
    x, (X, Y, Z) = pad_to_multiple(x, model.multiple)
    out = model(x)[0, 0, :X, :Y, :Z]
    return out.cpu().numpy().astype(np.float64)


def predict_density(model: TopoNetUNet3D, problem: Problem, device: str = "cpu", tta: bool = False) -> np.ndarray:
    """Predicción completa. `tta` = test-time augmentation con espejos (promedia 4 pasadas)."""
    feats = build_features(problem)
    logits = predict_logits(model, feats, device)
    if tta:
        from .features import flip_features

        acc = logits.copy()
        n = 1
        for ax in (0, 1, 2):
            lf = predict_logits(model, flip_features(feats, ax), device)
            acc += np.flip(lf, axis=ax)
            n += 1
        logits = acc / n
    return calibrate_volume(logits, problem)
