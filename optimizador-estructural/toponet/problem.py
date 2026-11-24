"""Definición del problema de optimización estructural.

Un `Problem` contiene todo lo que un optimizador necesita saber:

* el dominio de diseño voxelizado (qué vóxeles pertenecen a la pieza),
* las regiones no diseñables (que deben quedar macizas),
* las condiciones de contorno (apoyos) y las cargas, definidas en los NODOS
  de la malla de hexaedros,
* el material y la fracción de volumen objetivo.

Convenciones
------------
* Unidades: milímetros (mm), newtons (N) y megapascales (MPa = N/mm²).
  Con ellas los desplazamientos salen en mm y las tensiones en MPa.
* La rejilla de elementos tiene forma ``(nx, ny, nz)`` e índice ``[i, j, k]``
  que corresponde a los ejes ``x, y, z``.
* Los nodos forman una rejilla ``(nx+1, ny+1, nz+1)``.
* El nodo ``(i, j, k)`` está en ``origin + pitch * (i, j, k)``.
* El centro del elemento ``(i, j, k)`` está en ``origin + pitch * (i+0.5, j+0.5, k+0.5)``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import numpy as np


@dataclass
class Material:
    """Material lineal elástico (isótropo, o transversalmente isótropo si se imprime).

    Los campos de fatiga y anisotropía solo los usa el análisis avanzado
    (`toponet/physics`). Todos los valores de `MATERIALS` son ORIENTATIVOS: para una
    pieza real usa los de la ficha técnica de tu proveedor o, mejor, de ensayos.
    """

    name: str = "PLA"
    E: float = 3500.0  # módulo de Young [MPa]
    nu: float = 0.35  # coeficiente de Poisson [-]
    yield_strength: float = 50.0  # límite elástico [MPa]
    density: float = 1.24  # densidad [g/cm³]
    ultimate_strength: float = 55.0  # resistencia a tracción [MPa] (corrección de Goodman)
    fatigue_strength: float = 18.0  # amplitud de tensión resistida a `fatigue_cycles_ref` ciclos, R=-1 [MPa]
    fatigue_cycles_ref: float = 1e6
    fatigue_exponent: float = 10.0  # m de Basquin: S^m · N = cte
    # Impresión 3D por capas (FDM): material transversalmente isótropo
    layer_E_ratio: float = 0.85  # E perpendicular a las capas / E en el plano
    interlayer_strength_ratio: float = 0.55  # resistencia entre capas / resistencia en el plano

    @staticmethod
    def from_dict(d: dict) -> "Material":
        base = MATERIALS.get(d.get("name", ""), Material())
        vals = {k: d.get(k, getattr(base, k)) for k in Material.__dataclass_fields__}
        vals["name"] = str(vals["name"])
        for k, v in vals.items():
            if k != "name":
                vals[k] = float(v)
        return Material(**vals)


MATERIALS = {
    #                    nombre               E        nu    σy     ρ     Su     Sf    N_ref  m    Ez/E  capas
    "PLA": Material("PLA", 3500.0, 0.35, 50.0, 1.24, 55.0, 18.0, 1e6, 10.0, 0.85, 0.55),
    "PETG": Material("PETG", 2100.0, 0.38, 45.0, 1.27, 50.0, 14.0, 1e6, 10.0, 0.90, 0.60),
    "ABS": Material("ABS", 2200.0, 0.35, 40.0, 1.05, 42.0, 12.0, 1e6, 10.0, 0.85, 0.50),
    "Nylon PA12": Material("Nylon PA12", 1700.0, 0.39, 45.0, 1.01, 48.0, 18.0, 1e6, 12.0, 0.90, 0.60),
    "Aluminio 6061-T6": Material("Aluminio 6061-T6", 69000.0, 0.33, 276.0, 2.70, 310.0, 96.5, 5e8, 12.0, 1.0, 1.0),
    "Acero S235": Material("Acero S235", 210000.0, 0.30, 235.0, 7.85, 360.0, 180.0, 1e6, 10.0, 1.0, 1.0),
    "Titanio Ti6Al4V": Material("Titanio Ti6Al4V", 114000.0, 0.34, 880.0, 4.43, 950.0, 510.0, 1e7, 12.0, 1.0, 1.0),
}


@dataclass
class Region:
    """Región geométrica usada para definir apoyos o cargas desde la interfaz.

    kind:
        ``"fixed"`` (apoyo) o ``"load"`` (carga).
    shape:
        ``"sphere"`` -> ``center`` (mm) + ``radius`` (mm)
        ``"face"``   -> ``face`` en {"xmin","xmax","ymin","ymax","zmin","zmax"}
                         (la cara de la caja envolvente del dominio)
    dofs:
        Para apoyos: qué direcciones se bloquean (x, y, z).
    force:
        Para cargas: fuerza TOTAL en N, se reparte entre los nodos de la región.
    keep_solid:
        Si es True, los elementos de la región se marcan como no diseñables
        (siempre macizos). Muy recomendable: garantiza que la zona donde se
        atornilla o se aplica la carga no desaparece.
    """

    kind: str
    shape: str = "sphere"
    center: Sequence[float] = (0.0, 0.0, 0.0)
    radius: float = 5.0
    face: str = "xmin"
    dofs: Sequence[bool] = (True, True, True)
    force: Sequence[float] = (0.0, 0.0, -100.0)
    keep_solid: bool = True

    @staticmethod
    def from_dict(d: dict) -> "Region":
        return Region(
            kind=d["kind"],
            shape=d.get("shape", "sphere"),
            center=tuple(d.get("center", (0, 0, 0))),
            radius=float(d.get("radius", 5.0)),
            face=d.get("face", "xmin"),
            dofs=tuple(bool(v) for v in d.get("dofs", (True, True, True))),
            force=tuple(float(v) for v in d.get("force", (0, 0, -100))),
            keep_solid=bool(d.get("keep_solid", True)),
        )


@dataclass
class Problem:
    domain: np.ndarray  # bool (nx,ny,nz): vóxel dentro de la pieza
    fixed: np.ndarray  # bool (nx+1,ny+1,nz+1,3): GDL bloqueado
    forces: np.ndarray  # float (nx+1,ny+1,nz+1,3): fuerza nodal [N]
    passive_solid: Optional[np.ndarray] = None  # bool (nx,ny,nz)
    material: Material = field(default_factory=Material)
    volfrac: float = 0.3  # fracción del volumen ORIGINAL que se conserva
    pitch: float = 1.0  # tamaño de vóxel [mm]
    origin: np.ndarray = field(default_factory=lambda: np.zeros(3))
    name: str = "problema"

    def __post_init__(self) -> None:
        self.domain = np.asarray(self.domain, dtype=bool)
        if self.passive_solid is None:
            self.passive_solid = np.zeros_like(self.domain)
        self.passive_solid = np.asarray(self.passive_solid, dtype=bool) & self.domain
        self.origin = np.asarray(self.origin, dtype=float)

    # ------------------------------------------------------------------ util
    @property
    def shape(self):
        return self.domain.shape

    @property
    def n_domain(self) -> int:
        return int(self.domain.sum())

    @property
    def design(self) -> np.ndarray:
        """Elementos cuya densidad puede cambiar el optimizador."""
        return self.domain & ~self.passive_solid

    def element_centers(self) -> np.ndarray:
        nx, ny, nz = self.shape
        idx = np.stack(np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij"), -1)
        return self.origin + self.pitch * (idx + 0.5)

    def node_coords(self) -> np.ndarray:
        nx, ny, nz = self.shape
        idx = np.stack(
            np.meshgrid(np.arange(nx + 1), np.arange(ny + 1), np.arange(nz + 1), indexing="ij"), -1
        )
        return self.origin + self.pitch * idx

    def active_nodes(self, elements: Optional[np.ndarray] = None) -> np.ndarray:
        """Nodos que pertenecen a algún elemento activo (bool (nx+1,ny+1,nz+1))."""
        el = self.domain if elements is None else elements
        nodes = np.zeros(tuple(s + 1 for s in el.shape), dtype=bool)
        for a in (0, 1):
            for b in (0, 1):
                for c in (0, 1):
                    nodes[a : a + el.shape[0], b : b + el.shape[1], c : c + el.shape[2]] |= el
        return nodes

    def summary(self) -> dict:
        f = self.forces.reshape(-1, 3)
        return {
            "grid": list(self.shape),
            "pitch_mm": self.pitch,
            "elements_in_domain": self.n_domain,
            "passive_elements": int(self.passive_solid.sum()),
            "fixed_dofs": int(self.fixed.sum()),
            "loaded_nodes": int((np.abs(f).sum(1) > 0).sum()),
            "total_force_N": f.sum(0).tolist(),
            "volfrac": self.volfrac,
            "material": self.material.name,
        }


# ---------------------------------------------------------------------------
# Construcción de condiciones de contorno a partir de regiones
# ---------------------------------------------------------------------------

def _region_node_mask(problem: Problem, region: Region, active: np.ndarray) -> np.ndarray:
    coords = problem.node_coords()
    if region.shape == "sphere":
        d = np.linalg.norm(coords - np.asarray(region.center, float), axis=-1)
        mask = (d <= region.radius) & active
        if not mask.any():  # si el radio es menor que un vóxel, coge el nodo activo más cercano
            d2 = np.where(active, d, np.inf)
            mask = np.zeros_like(active)
            mask[np.unravel_index(np.argmin(d2), d2.shape)] = True
        return mask
    if region.shape == "face":
        idx = np.argwhere(active)
        axis = "xyz".index(region.face[0])
        lo, hi = idx[:, axis].min(), idx[:, axis].max()
        target = lo if region.face.endswith("min") else hi
        sl = [slice(None)] * 3
        sl[axis] = target
        mask = np.zeros_like(active)
        mask[tuple(sl)] = active[tuple(sl)]
        return mask
    raise ValueError(f"forma de región desconocida: {region.shape}")


def _nodes_to_elements(node_mask: np.ndarray) -> np.ndarray:
    """Elementos que tocan alguno de los nodos marcados."""
    nx, ny, nz = (s - 1 for s in node_mask.shape)
    el = np.zeros((nx, ny, nz), dtype=bool)
    for a in (0, 1):
        for b in (0, 1):
            for c in (0, 1):
                el |= node_mask[a : a + nx, b : b + ny, c : c + nz]
    return el


def apply_regions(problem: Problem, regions: List[Region]) -> Problem:
    """Rellena `fixed`, `forces` y `passive_solid` a partir de una lista de regiones."""
    active = problem.active_nodes()
    fixed = np.zeros(active.shape + (3,), dtype=bool)
    forces = np.zeros(active.shape + (3,), dtype=float)
    passive = problem.passive_solid.copy()
    for r in regions:
        m = _region_node_mask(problem, r, active)
        if r.kind == "fixed":
            for d in range(3):
                if r.dofs[d]:
                    fixed[..., d] |= m
        elif r.kind == "load":
            n = max(int(m.sum()), 1)
            forces[m] += np.asarray(r.force, float) / n
        else:
            raise ValueError(f"tipo de región desconocido: {r.kind}")
        if r.keep_solid:
            passive |= _nodes_to_elements(m) & problem.domain
    problem.fixed = fixed
    problem.forces = forces
    problem.passive_solid = passive
    return problem
