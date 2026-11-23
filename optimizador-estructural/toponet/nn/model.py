"""TopoNet: U-Net 3D totalmente convolucional para predecir la topología óptima.

    entrada  (B, C=9, X, Y, Z)  -> rasgos del problema (ver features.py)
    salida   (B, 1,   X, Y, Z)  -> logits de densidad (sigmoid -> [0, 1])

Arquitectura (depth=3, base=16):

    9 ─► [16] ──────────────────────────────────────► [16] ─► 1
           │ pool                                  ▲ up
           ▼                                       │
          [32] ───────────────────────────────► [32]
           │ pool                              ▲ up
           ▼                                   │
          [64] ─────────────────────────► [64]
           │ pool                        ▲ up
           ▼                             │
          [128]  ── cuello de botella ───┘

* Bloques: (Conv3d 3x3x3 -> GroupNorm -> SiLU) x 2 con conexión residual.
* Las conexiones de salto (skip) llevan el detalle fino al decodificador.
* Al ser totalmente convolucional acepta cualquier tamaño de rejilla múltiplo
  de 2^depth (se rellena con ceros automáticamente en `predict`).

Teoría en `guia/05-redes-neuronales.md`.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


def _groups(c: int) -> int:
    for g in (8, 4, 2, 1):
        if c % g == 0:
            return g
    return 1


class ResBlock(nn.Module):
    def __init__(self, cin: int, cout: int, dropout: float = 0.0):
        super().__init__()
        self.conv1 = nn.Conv3d(cin, cout, 3, padding=1, bias=False)
        self.norm1 = nn.GroupNorm(_groups(cout), cout)
        self.conv2 = nn.Conv3d(cout, cout, 3, padding=1, bias=False)
        self.norm2 = nn.GroupNorm(_groups(cout), cout)
        self.act = nn.SiLU()
        self.drop = nn.Dropout3d(dropout) if dropout > 0 else nn.Identity()
        self.skip = nn.Conv3d(cin, cout, 1) if cin != cout else nn.Identity()

    def forward(self, x):
        h = self.act(self.norm1(self.conv1(x)))
        h = self.drop(h)
        h = self.norm2(self.conv2(h))
        return self.act(h + self.skip(x))


class TopoNetUNet3D(nn.Module):
    def __init__(self, in_channels: int = 9, base: int = 16, depth: int = 3, dropout: float = 0.0):
        super().__init__()
        self.config = dict(in_channels=in_channels, base=base, depth=depth, dropout=dropout)
        self.depth = depth
        chs = [base * 2**i for i in range(depth + 1)]
        self.stem = ResBlock(in_channels, chs[0])
        self.down = nn.ModuleList()
        self.enc = nn.ModuleList()
        for i in range(depth):
            self.down.append(nn.Conv3d(chs[i], chs[i], 2, stride=2))  # downsampling aprendido
            self.enc.append(ResBlock(chs[i], chs[i + 1], dropout if i == depth - 1 else 0.0))
        self.up = nn.ModuleList()
        self.dec = nn.ModuleList()
        for i in reversed(range(depth)):
            self.up.append(nn.ConvTranspose3d(chs[i + 1], chs[i], 2, stride=2))
            self.dec.append(ResBlock(chs[i] * 2, chs[i]))
        self.head = nn.Conv3d(chs[0], 1, 1)

    @property
    def multiple(self) -> int:
        return 2**self.depth

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.stem(x)
        skips = [h]
        for down, enc in zip(self.down, self.enc):
            h = enc(down(h))
            skips.append(h)
        skips.pop()  # el último es el cuello de botella
        for up, dec in zip(self.up, self.dec):
            h = up(h)
            h = dec(torch.cat([h, skips.pop()], dim=1))
        return self.head(h)


def pad_to_multiple(x: torch.Tensor, m: int):
    """Rellena (B,C,X,Y,Z) con ceros hasta múltiplos de m. Devuelve (x, recorte)."""
    X, Y, Z = x.shape[-3:]
    px, py, pz = (-X) % m, (-Y) % m, (-Z) % m
    x = F.pad(x, (0, pz, 0, py, 0, px))
    return x, (X, Y, Z)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def save_checkpoint(path: str, model: TopoNetUNet3D, extra: dict) -> None:
    torch.save({"config": model.config, "state_dict": model.state_dict(), **extra}, path)


def load_checkpoint(path: str, device: str = "cpu"):
    ck = torch.load(path, map_location=device, weights_only=False)
    model = TopoNetUNet3D(**ck["config"])
    model.load_state_dict(ck["state_dict"])
    model.eval().to(device)
    return model, ck
