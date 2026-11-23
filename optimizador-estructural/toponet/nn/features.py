"""Codificación del problema como tensor de entrada para la red.

Canales (todos con la resolución de la rejilla de elementos):

 0 dominio            1 dentro de la pieza, 0 fuera
 1 no_diseñable       1 donde el material es obligatorio
 2 apoyos             fracción de GDL bloqueados de los nodos del elemento
 3-5 Fx, Fy, Fz       fuerza en el elemento, normalizada por el máximo
 6 fraccion_volumen   constante = volfrac (la "consigna" de cuánto material dejar)
 7 energia_solido     log10 de la energía de deformación de la pieza MACIZA (normalizada)
 8 von_mises_solido   tensión de von Mises de la pieza maciza / máximo

Los canales 7-8 son "rasgos físicos": un único análisis FEM de la pieza original
le dice a la red por dónde circulan las cargas. Es la clave para que generalice
a geometrías y cargas que no ha visto (ver guía, capítulo 5).

Todo se normaliza para que el resultado sea INVARIANTE a la escala de la carga,
al módulo de Young y al tamaño de vóxel: en elasticidad lineal la topología
óptima no depende de esos valores.
"""
from __future__ import annotations

import numpy as np

from ..fem import HexMesh
from ..problem import Problem

FEATURE_NAMES = [
    "dominio",
    "no_diseñable",
    "apoyos",
    "Fx",
    "Fy",
    "Fz",
    "fraccion_volumen",
    "energia_solido",
    "von_mises_solido",
]
N_FEATURES = len(FEATURE_NAMES)


def _node_to_element_mean(node_field: np.ndarray) -> np.ndarray:
    nx, ny, nz = (s - 1 for s in node_field.shape[:3])
    out = np.zeros((nx, ny, nz) + node_field.shape[3:])
    for a in (0, 1):
        for b in (0, 1):
            for c in (0, 1):
                out += node_field[a : a + nx, b : b + ny, c : c + nz]
    return out / 8.0


def build_features(problem: Problem) -> np.ndarray:
    dom = problem.domain
    feats = np.zeros((N_FEATURES,) + dom.shape, dtype=np.float32)
    feats[0] = dom
    feats[1] = problem.passive_solid
    feats[2] = _node_to_element_mean(problem.fixed.astype(float)).mean(-1) * dom
    fe = _node_to_element_mean(problem.forces) * 8.0  # suma de las fuerzas de sus nodos
    fmax = np.abs(fe).max()
    if fmax > 0:
        fe = fe / fmax
    feats[3:6] = np.moveaxis(fe, -1, 0) * dom
    feats[6] = problem.volfrac * dom

    # ---- rasgos físicos: análisis de la pieza maciza con material unitario
    mesh = HexMesh(dom, problem.material.nu, problem.fixed)
    E_el = np.ones(mesh.n_elements)
    fnorm = np.abs(problem.forces).max()
    forces = problem.forces / fnorm if fnorm > 0 else problem.forces
    res = mesh.solve(E_el, 1.0, forces)
    ce = res.ce
    cmax = ce[dom].max() if dom.any() else 0.0
    if cmax > 0:
        sed = np.log10(np.maximum(ce / cmax, 1e-6)) / 6.0 + 1.0  # [0, 1]
        feats[7] = sed * dom
    vm = mesh.von_mises(res.u, E_el, 1.0)
    vmax = vm[dom].max() if dom.any() else 0.0
    if vmax > 0:
        feats[8] = np.sqrt(vm / vmax) * dom
    return feats


def flip_features(feats: np.ndarray, axis: int) -> np.ndarray:
    """Simetría de espejo en el eje `axis` (0,1,2): invierte también la componente
    de la fuerza correspondiente. Útil para aumentación de datos."""
    out = np.flip(feats, axis=axis + 1).copy()
    out[3 + axis] *= -1
    return out


def swap_yz_features(feats: np.ndarray) -> np.ndarray:
    """Intercambia los ejes y-z (rotación/reflexión válida si ny == nz)."""
    out = np.swapaxes(feats, 2, 3).copy()
    out[[4, 5]] = out[[5, 4]]
    return out
