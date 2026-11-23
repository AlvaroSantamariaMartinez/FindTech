"""Funciones de pérdida para entrenar TopoNet.

L = w_bce  * BCE ponderada por energía      (forma, con más peso donde trabaja el material)
  + w_dice * (1 - Dice suave)               (solape global, robusto al desbalance 0/1)
  + w_vol  * (V_pred - V_obj)^2             (respetar la cantidad de material)
  + w_tv   * variación total                (suavidad, castiga el "ruido" de vóxeles sueltos)

Todas se calculan SOLO dentro del dominio de diseño (canal 0 de la entrada).
Ver la deducción y el porqué de cada término en `guia/06-sistema-entrenamiento.md`.
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F


@dataclass
class LossWeights:
    bce: float = 1.0
    dice: float = 0.5
    vol: float = 5.0
    tv: float = 0.02
    energy_alpha: float = 2.0  # cuánto pesa la energía de deformación en la BCE


def topo_loss(logits: torch.Tensor, target: torch.Tensor, x: torch.Tensor, w: LossWeights):
    """logits/target: (B,1,X,Y,Z); x: entrada (B,C,X,Y,Z). Devuelve (total, dict de componentes)."""
    mask = x[:, 0:1]  # dominio
    energy = x[:, 7:8]  # log-energía normalizada de la pieza maciza [0,1]
    passive = x[:, 1:2]
    vf = x[:, 6:7]
    pred = torch.sigmoid(logits)
    n = mask.sum(dim=(1, 2, 3, 4)).clamp_min(1.0)

    # 1) BCE ponderada: los errores donde fluye la carga importan más
    weight = mask * (1.0 + w.energy_alpha * energy)
    bce = F.binary_cross_entropy_with_logits(logits, target, weight=weight, reduction="none")
    bce = (bce.sum(dim=(1, 2, 3, 4)) / weight.sum(dim=(1, 2, 3, 4)).clamp_min(1.0)).mean()

    # 2) Dice suave
    inter = (pred * target * mask).sum(dim=(1, 2, 3, 4))
    den = ((pred + target) * mask).sum(dim=(1, 2, 3, 4)).clamp_min(1e-6)
    dice = (1 - 2 * inter / den).mean()

    # 3) Volumen (incluye las zonas no diseñables, que valen 1)
    pred_full = torch.where(passive > 0.5, torch.ones_like(pred), pred) * mask
    v_pred = pred_full.sum(dim=(1, 2, 3, 4)) / n
    v_obj = (vf * mask).sum(dim=(1, 2, 3, 4)) / n
    vol = ((v_pred - v_obj) ** 2).mean()

    # 4) Variación total anisótropa dentro del dominio
    tv = 0.0
    for d in (2, 3, 4):
        diff = torch.diff(pred, dim=d).abs()
        m = torch.minimum(mask.narrow(d, 1, mask.shape[d] - 1), mask.narrow(d, 0, mask.shape[d] - 1))
        tv = tv + (diff * m).sum(dim=(1, 2, 3, 4)) / n
    tv = tv.mean()

    total = w.bce * bce + w.dice * dice + w.vol * vol + w.tv * tv
    return total, {"bce": bce.item(), "dice": dice.item(), "vol": vol.item(), "tv": float(tv.detach())}


@torch.no_grad()
def batch_metrics(logits: torch.Tensor, target: torch.Tensor, x: torch.Tensor) -> dict:
    """Métricas geométricas (las físicas se calculan con FEM en evaluate.py)."""
    mask = x[:, 0:1] > 0.5
    pred = torch.sigmoid(logits)
    pb = (pred > 0.5) & mask
    tb = (target > 0.5) & mask
    inter = (pb & tb).sum(dim=(1, 2, 3, 4)).float()
    union = (pb | tb).sum(dim=(1, 2, 3, 4)).float().clamp_min(1)
    mae = ((pred - target).abs() * mask).sum(dim=(1, 2, 3, 4)) / mask.sum(dim=(1, 2, 3, 4)).clamp_min(1)
    vp = (pred * mask).sum(dim=(1, 2, 3, 4)) / mask.sum(dim=(1, 2, 3, 4)).clamp_min(1)
    vt = (target * mask).sum(dim=(1, 2, 3, 4)) / mask.sum(dim=(1, 2, 3, 4)).clamp_min(1)
    return {
        "iou": (inter / union).mean().item(),
        "mae": mae.mean().item(),
        "vol_err": (vp - vt).abs().mean().item(),
    }
