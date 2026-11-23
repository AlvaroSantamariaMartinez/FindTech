"""Geometrías biomiméticas voxelizadas.

Cada órgano se representa como una rejilla 3D ``mat[z, y, x]`` con etiquetas:
``0`` vacío, ``1`` material A (estructural, extrusor E1),
``2`` material B (biotinta celular, extrusor E2).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

VACIO, MAT_A, MAT_B = 0, 1, 2


@dataclass
class Geometria:
    nombre: str
    mat: np.ndarray  # int8 (nz, ny, nx)
    res_xy: float  # mm por vóxel en XY (= ancho nominal de filamento)
    altura_capa: float  # mm por capa

    @property
    def forma(self) -> tuple[int, int, int]:
        return self.mat.shape  # type: ignore[return-value]

    @property
    def altura_mm(self) -> float:
        return self.mat.shape[0] * self.altura_capa

    def coords_xy(self) -> tuple[np.ndarray, np.ndarray]:
        """Centros (x, y) en mm de cada columna, centrados en el origen."""
        _, ny, nx = self.mat.shape
        x = (np.arange(nx) + 0.5) * self.res_xy - nx * self.res_xy / 2
        y = (np.arange(ny) + 0.5) * self.res_xy - ny * self.res_xy / 2
        return x, y

    def volumen_mm3(self, etiqueta: int | None = None) -> float:
        m = self.mat > 0 if etiqueta is None else self.mat == etiqueta
        return float(m.sum()) * self.res_xy**2 * self.altura_capa


# ---------------------------------------------------------------------------
# Plantillas de órganos / tejidos
# ---------------------------------------------------------------------------


def _vaso(X, Y, Z):
    """Vaso sanguíneo: endotelio celular (B) + pared estructural (A), luz hueca."""
    r = np.hypot(X, Y)
    lab = np.zeros(X.shape, np.int8)
    lab[(r >= 1.4) & (r < 2.0)] = MAT_B
    lab[(r >= 2.0) & (r < 3.2)] = MAT_A
    return lab, 5.0


def _lobulo_hepatico(X, Y, Z):
    """Lóbulo hepático hexagonal: vena central, sinusoides radiales (A) y hepatocitos (B)."""
    R = 3.6
    ax, ay = np.abs(X), np.abs(Y)
    dentro = (ay <= R * np.sqrt(3) / 2) & (np.sqrt(3) * ax + ay <= np.sqrt(3) * R)
    # distancia al borde del hexágono (aprox. por la arista más cercana)
    d_borde = np.minimum(R * np.sqrt(3) / 2 - ay, (np.sqrt(3) * R - np.sqrt(3) * ax - ay) / 2)
    r = np.hypot(X, Y)
    th = np.arctan2(Y, X)
    d_radio = np.full(X.shape, np.inf)
    for k in range(6):
        phi = np.deg2rad(30 + 60 * k)
        proy = r * np.cos(th - phi)
        d = np.where(proy > 0, np.abs(r * np.sin(th - phi)), np.inf)
        d_radio = np.minimum(d_radio, d)
    lab = np.zeros(X.shape, np.int8)
    lab[dentro] = MAT_B
    lab[dentro & ((d_radio < 0.3) | (d_borde < 0.4))] = MAT_A
    lab[r < 0.6] = VACIO  # vena central
    return lab, 4.0


def _parche_cardiaco(X, Y, Z):
    """Parche cardíaco: retícula estructural (A) con poros alternos rellenos de cardiomiocitos (B)."""
    paso, ancho, L = 1.5, 0.5, 3.75
    dentro = (np.abs(X) <= L) & (np.abs(Y) <= L)
    fx = np.mod(X + L, paso)
    fy = np.mod(Y + L, paso)
    barra = (fx < ancho) | (fy < ancho)
    i = np.floor((X + L) / paso).astype(int)
    j = np.floor((Y + L) / paso).astype(int)
    lab = np.zeros(X.shape, np.int8)
    lab[dentro & ~barra & ((i + j) % 2 == 0)] = MAT_B
    lab[dentro & barra] = MAT_A
    return lab, 2.0


ORGANOS = {
    "vaso": _vaso,
    "lobulo_hepatico": _lobulo_hepatico,
    "parche_cardiaco": _parche_cardiaco,
}


def generar(nombre: str, altura_capa: float = 0.3, res_xy: float = 0.25, tam_mm: float = 8.0) -> Geometria:
    if nombre not in ORGANOS:
        raise KeyError(f"Órgano desconocido '{nombre}'. Opciones: {', '.join(ORGANOS)}")
    n = int(round(tam_mm / res_xy))
    c = (np.arange(n) + 0.5) * res_xy - tam_mm / 2
    Y, X = np.meshgrid(c, c, indexing="ij")
    lab2d, altura = ORGANOS[nombre](X, Y, None)
    nz = max(1, int(round(altura / altura_capa)))
    mat = np.repeat(lab2d[None], nz, axis=0).astype(np.int8)
    return Geometria(nombre, mat, res_xy, altura_capa)


def desde_array(nombre: str, mat: np.ndarray, res_xy: float, altura_capa: float) -> Geometria:
    """Geometría personalizada (p. ej. segmentada de imágenes médicas)."""
    mat = np.asarray(mat, dtype=np.int8)
    if mat.ndim != 3 or not np.isin(mat, (VACIO, MAT_A, MAT_B)).all():
        raise ValueError("mat debe ser 3D (z, y, x) con valores 0, 1 o 2")
    return Geometria(nombre, mat, res_xy, altura_capa)


def ascii_capa(capa: np.ndarray) -> str:
    """Representación de texto de una capa (para la terminal)."""
    simb = {VACIO: "·", MAT_A: "█", MAT_B: "▒"}
    return "\n".join("".join(simb[int(v)] for v in fila) for fila in capa[::-1])
