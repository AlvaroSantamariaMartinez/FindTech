"""Generación de datos sintéticos con el simulador (gemelo digital)."""

from __future__ import annotations

import math
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from ..config import MODOS, PARAMS_CONTINUOS, RANGOS, ParametrosProceso
from ..geometria import ORGANOS
from ..simulador import simular

ORGANOS_LISTA = tuple(ORGANOS)
OBJETIVOS = ("fidelidad_iou", "viabilidad", "fraccion_curada", "conversion_media",
             "error_altura", "log10_tiempo", "riesgo_obstruccion", "puntuacion")
NOMBRES_ENTRADA = PARAMS_CONTINUOS + tuple(f"modo={m}" for m in MODOS) + tuple(f"organo={o}" for o in ORGANOS_LISTA)


def parametros_desde_unitario(u: np.ndarray, modo: str) -> ParametrosProceso:
    """u ∈ [0,1]^8 → parámetros físicos (escala log para rangos amplios)."""
    vals = {}
    for ui, nombre in zip(u, PARAMS_CONTINUOS):
        lo, hi = RANGOS[nombre]
        vals[nombre] = float(math.exp(math.log(lo) + float(np.clip(ui, 0, 1)) * (math.log(hi) - math.log(lo))))
    modo_uv, estrategia = modo.split("+")
    return ParametrosProceso(**vals, modo_uv=modo_uv, estrategia=estrategia)


def unitario_desde_parametros(p: ParametrosProceso) -> np.ndarray:
    u = []
    for nombre in PARAMS_CONTINUOS:
        lo, hi = RANGOS[nombre]
        u.append((math.log(getattr(p, nombre)) - math.log(lo)) / (math.log(hi) - math.log(lo)))
    return np.clip(np.array(u), 0, 1)


def codificar(u: np.ndarray, modo: str, organo: str) -> np.ndarray:
    oh_m = np.array([m == modo for m in MODOS], float)
    oh_o = np.array([o == organo for o in ORGANOS_LISTA], float)
    return np.concatenate([u, oh_m, oh_o])


def objetivos_de(metricas: dict) -> np.ndarray:
    return np.array([
        metricas["fidelidad_iou"], metricas["viabilidad"], metricas["fraccion_curada"],
        metricas["conversion_media"], metricas["error_altura"],
        math.log10(max(metricas["tiempo_s"], 1.0)), metricas["riesgo_obstruccion"],
        metricas["puntuacion"],
    ])


def _muestra(args):
    semilla, organo = args
    rng = np.random.default_rng(semilla)
    u = rng.random(len(PARAMS_CONTINUOS))
    modo = MODOS[rng.integers(len(MODOS))]
    organo = organo or ORGANOS_LISTA[rng.integers(len(ORGANOS_LISTA))]
    r = simular(organo, parametros_desde_unitario(u, modo))
    return codificar(u, modo, organo), objetivos_de(r.metricas)


def generar_dataset(n: int, semilla: int = 0, organo: str | None = None,
                    procesos: int | None = None, verbose: bool = True):
    procesos = procesos or os.cpu_count() or 1
    tareas = [(semilla * 1_000_003 + i, organo) for i in range(n)]
    X, Y = [], []
    with ProcessPoolExecutor(procesos) as ex:
        for i, (x, y) in enumerate(ex.map(_muestra, tareas, chunksize=16)):
            X.append(x)
            Y.append(y)
            if verbose and (i + 1) % max(1, n // 10) == 0:
                print(f"  {i + 1}/{n} simulaciones")
    return np.array(X), np.array(Y)


def guardar_dataset(ruta: str, X: np.ndarray, Y: np.ndarray) -> None:
    np.savez_compressed(ruta, X=X, Y=Y, entradas=np.array(NOMBRES_ENTRADA), objetivos=np.array(OBJETIVOS))


def cargar_dataset(ruta: str):
    d = np.load(ruta)
    return d["X"], d["Y"]
