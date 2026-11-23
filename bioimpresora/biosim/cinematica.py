"""Cinemática de los brazos: trayectorias lineales a tramos y detección de colisiones."""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np


def tiempo_viaje(d: float, v: float, a: float) -> float:
    """Duración de un desplazamiento con perfil trapezoidal de velocidad."""
    if d <= 0:
        return 0.0
    d_acel = v * v / a
    if d >= d_acel:
        return d / v + v / a
    return 2.0 * math.sqrt(d / a)


class Trayectoria:
    """Posición (x, y) de la punta de un brazo como función lineal a tramos del tiempo."""

    def __init__(self, t0: float, pos: tuple[float, float]):
        self.t = [t0]
        self.x = [pos[0]]
        self.y = [pos[1]]

    @property
    def fin(self) -> float:
        return self.t[-1]

    @property
    def pos(self) -> tuple[float, float]:
        return self.x[-1], self.y[-1]

    def mover(self, x: float, y: float, duracion: float) -> None:
        self.t.append(self.t[-1] + max(duracion, 0.0))
        self.x.append(x)
        self.y.append(y)

    def viajar(self, x: float, y: float, v: float, a: float) -> float:
        d = math.hypot(x - self.x[-1], y - self.y[-1])
        dur = tiempo_viaje(d, v, a)
        if d > 0:
            self.mover(x, y, dur)
        return dur

    def esperar_hasta(self, t: float) -> None:
        if t > self.fin:
            self.mover(self.x[-1], self.y[-1], t - self.fin)

    def desplazada(self, dt: float) -> "Trayectoria":
        tr = Trayectoria(self.t[0] + dt, (self.x[0], self.y[0]))
        tr.t = [ti + dt for ti in self.t]
        tr.x, tr.y = list(self.x), list(self.y)
        return tr

    def anexar(self, otra: "Trayectoria") -> None:
        """Concatena otra trayectoria que empieza donde/cuando termina ésta."""
        self.esperar_hasta(otra.t[0])
        self.t += otra.t[1:]
        self.x += otra.x[1:]
        self.y += otra.y[1:]

    def posiciones(self, ts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        t = np.asarray(self.t)
        return np.interp(ts, t, self.x), np.interp(ts, t, self.y)


def distancia_minima(trays: dict[str, Trayectoria], radios: dict[str, float],
                     t0: float, t1: float, dt: float = 0.1) -> tuple[float, int]:
    """Holgura mínima entre cabezales y nº de instantes en colisión en [t0, t1]."""
    if t1 <= t0:
        return math.inf, 0
    ts = np.arange(t0, t1 + dt, dt)
    pos = {k: tr.posiciones(ts) for k, tr in trays.items()}
    holgura_min, choques = math.inf, 0
    for a, b in combinations(trays, 2):
        d = np.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]) - (radios[a] + radios[b])
        holgura_min = min(holgura_min, float(d.min()))
        choques += int((d < 0).sum())
    return holgura_min, choques
