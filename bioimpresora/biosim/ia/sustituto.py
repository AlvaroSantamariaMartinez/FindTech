"""Modelo sustituto (surrogate) profundo y diseño inverso de parámetros.

El modelo aprende  parámetros de proceso + modo + órgano  →  métricas de calidad,
y sustituye al simulador (≈1000× más rápido) para optimizar la impresión por
descenso de gradiente sobre la propia red.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import MODOS, PARAMS_CONTINUOS
from ..simulador import simular
from .datos import OBJETIVOS, codificar, parametros_desde_unitario
from .red import RedNeuronal

N_CONT = len(PARAMS_CONTINUOS)
I_PUNT = OBJETIVOS.index("puntuacion")
I_VIAB = OBJETIVOS.index("viabilidad")
I_IOU = OBJETIVOS.index("fidelidad_iou")


class ModeloSustituto:
    def __init__(self, red: RedNeuronal, mx, sx, my, sy):
        self.red, self.mx, self.sx, self.my, self.sy = red, mx, sx, my, sy

    # ----------------------------------------------------------- entrenamiento
    @classmethod
    def entrenar(cls, X, Y, ocultas=(128, 128, 64), epocas=400, lr=2e-3, semilla=0,
                 frac_val=0.15, verbose=True):
        rng = np.random.default_rng(semilla)
        perm = rng.permutation(len(X))
        n_val = max(1, int(len(X) * frac_val))
        iv, it = perm[:n_val], perm[n_val:]
        mx, sx = X[it].mean(0), X[it].std(0) + 1e-8
        my, sy = Y[it].mean(0), Y[it].std(0) + 1e-8
        red = RedNeuronal([X.shape[1], *ocultas, Y.shape[1]], semilla=semilla)
        Xn, Yn = (X - mx) / sx, (Y - my) / sy
        historia = red.entrenar(Xn[it], Yn[it], Xn[iv], Yn[iv], epocas=epocas, lr=lr,
                                semilla=semilla, verbose=verbose)
        modelo = cls(red, mx, sx, my, sy)
        return modelo, modelo.evaluar(X[iv], Y[iv]), historia

    def predecir(self, X: np.ndarray) -> np.ndarray:
        return self.red.predecir((X - self.mx) / self.sx) * self.sy + self.my

    def evaluar(self, X, Y) -> dict[str, dict[str, float]]:
        P = self.predecir(X)
        out = {}
        for j, nombre in enumerate(OBJETIVOS):
            ss_res = ((P[:, j] - Y[:, j]) ** 2).sum()
            ss_tot = ((Y[:, j] - Y[:, j].mean()) ** 2).sum() + 1e-12
            out[nombre] = {"R2": float(1 - ss_res / ss_tot), "MAE": float(np.abs(P[:, j] - Y[:, j]).mean())}
        return out

    # ----------------------------------------------------------- persistencia
    def guardar(self, ruta: str) -> None:
        np.savez(ruta, mx=self.mx, sx=self.sx, my=self.my, sy=self.sy, **self.red.estado())

    @classmethod
    def cargar(cls, ruta: str) -> "ModeloSustituto":
        d = dict(np.load(ruta))
        return cls(RedNeuronal.desde_estado(d), d["mx"], d["sx"], d["my"], d["sy"])

    # ----------------------------------------------------------- diseño inverso
    def _objetivo_y_grad(self, U, modo, organo, viab_min, iou_min):
        X = np.stack([codificar(u, modo, organo) for u in U])
        Xn = (X - self.mx) / self.sx
        # gradientes de las tres salidas que intervienen
        y, g_p = self.red.gradiente_entrada(Xn, _onehot(I_PUNT, len(OBJETIVOS)))
        _, g_v = self.red.gradiente_entrada(Xn, _onehot(I_VIAB, len(OBJETIVOS)))
        _, g_i = self.red.gradiente_entrada(Xn, _onehot(I_IOU, len(OBJETIVOS)))
        Y = y * self.sy + self.my
        J = Y[:, I_PUNT].copy()
        G = g_p * self.sy[I_PUNT]
        pen = 5.0
        for idx, g, minimo in ((I_VIAB, g_v, viab_min), (I_IOU, g_i, iou_min)):
            if minimo is None:
                continue
            falta = minimo - Y[:, idx]
            activo = falta > 0
            J -= pen * np.where(activo, falta, 0)
            G += pen * activo[:, None] * g * self.sy[idx]
        G = G / self.sx  # cadena: X normalizado → X
        return J, G[:, :N_CONT], Y

    def optimizar(self, organo: str, n_inicios=64, pasos=200, paso=0.02, modos=MODOS,
                  viab_min: float | None = None, iou_min: float | None = None,
                  semilla=0, validar_top=3):
        rng = np.random.default_rng(semilla)
        candidatos = []
        for modo in modos:
            U = rng.random((n_inicios, N_CONT))
            m, v = np.zeros_like(U), np.zeros_like(U)
            for t in range(1, pasos + 1):  # ascenso con Adam proyectado en [0,1]
                _, G, _ = self._objetivo_y_grad(U, modo, organo, viab_min, iou_min)
                m = 0.9 * m + 0.1 * G
                v = 0.999 * v + 0.001 * G * G
                U = np.clip(U + paso * (m / (1 - 0.9**t)) / (np.sqrt(v / (1 - 0.999**t)) + 1e-8), 0, 1)
            J, _, Y = self._objetivo_y_grad(U, modo, organo, viab_min, iou_min)
            for k in np.argsort(-J)[:validar_top]:
                candidatos.append((float(J[k]), modo, U[k].copy(), Y[k].copy()))
        candidatos.sort(key=lambda c: -c[0])
        # validación de los mejores candidatos con el simulador físico
        validados = []
        for J, modo, u, y in candidatos[: validar_top * len(modos)]:
            p = parametros_desde_unitario(u, modo)
            r = simular(organo, p)
            validados.append(ResultadoOptimizacion(p, J, dict(zip(OBJETIVOS, y)), r.metricas))
        validados.sort(key=lambda c: -_objetivo_real(c.metricas_simuladas, viab_min, iou_min))
        return validados


def _onehot(i, n):
    v = np.zeros(n)
    v[i] = 1.0
    return v


def _objetivo_real(m, viab_min, iou_min):
    J = m["puntuacion"]
    if viab_min is not None:
        J -= 5 * max(0.0, viab_min - m["viabilidad"])
    if iou_min is not None:
        J -= 5 * max(0.0, iou_min - m["fidelidad_iou"])
    return J


@dataclass
class ResultadoOptimizacion:
    params: object
    objetivo_predicho: float
    prediccion: dict
    metricas_simuladas: dict
