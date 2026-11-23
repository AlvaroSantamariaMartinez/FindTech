"""Modelo base incluido: optimización topológica SIMP clásica (basada en física).

Es la referencia contra la que comparar tu red neuronal: lenta (decenas de
análisis FEM) pero fiable. Además genera las etiquetas del dataset.
"""
from __future__ import annotations

from ..plugins import OptimizerPlugin, Param, register
from ..simp import run_simp


@register
class SimpBaseline(OptimizerPlugin):
    id = "simp"
    name = "SIMP clásico (base)"
    kind = "clásico"
    description = (
        "Optimización topológica por densidades (SIMP + filtro de densidad + proyección "
        "Heaviside + criterios de optimalidad). Minimiza la flexibilidad (maximiza la "
        "rigidez) con la fracción de volumen indicada. Lento pero con garantías físicas."
    )
    params = [
        Param("max_iter", "int", 60, "Iteraciones máximas", min=5, max=300, step=5,
              help="Cada iteración es un análisis FEM completo."),
        Param("penal", "float", 3.0, "Penalización p", min=1.0, max=5.0, step=0.5,
              help="Exponente SIMP: castiga las densidades intermedias."),
        Param("rmin", "float", 1.5, "Radio de filtro (vóxeles)", min=1.0, max=4.0, step=0.1,
              help="Controla el grosor mínimo de los miembros."),
        Param("projection", "bool", True, "Proyección Heaviside",
              help="Empuja el diseño hacia 0/1 (más nítido, más fácil de fabricar)."),
    ]

    def optimize(self, problem, params, progress):
        res = run_simp(
            problem,
            max_iter=params["max_iter"],
            penal=params["penal"],
            rmin=params["rmin"],
            projection=params["projection"],
            progress=progress,
        )
        return res.density
