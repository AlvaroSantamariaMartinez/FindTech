"""Validación estructural común para CUALQUIER diseño, venga del modelo que venga.

Esta es la pieza que garantiza que la comparación entre modelos es justa: todos
los resultados se binarizan (lo que se fabricaría de verdad), se limpian y se
analizan con el mismo FEM.

Comprobaciones de integridad (ver `guia/07-integridad-y-validacion.md`):
  1. Camino de carga: todas las cargas llegan a algún apoyo a través de material.
  2. Islas: no hay trozos de material flotando (se eliminan y se informa).
  3. Resistencia: factor de seguridad frente al límite elástico.
  4. Rigidez: flexibilidad y desplazamiento máximo.
  5. Fabricabilidad básica: proporción de miembros de 1 vóxel de grosor.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
from scipy import ndimage

from .fem import HexMesh
from .problem import Problem

FACE_STRUCT = ndimage.generate_binary_structure(3, 1)  # conectividad por caras (6 vecinos)


@dataclass
class Evaluation:
    metrics: Dict[str, float]
    checks: List[dict]
    solid: np.ndarray  # diseño final binarizado y limpio
    von_mises: np.ndarray  # MPa por elemento
    displacement: np.ndarray  # |u| por elemento (media de sus nodos) [mm]
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"metrics": self.metrics, "checks": self.checks}


def _element_touches(node_mask: np.ndarray) -> np.ndarray:
    nx, ny, nz = (s - 1 for s in node_mask.shape)
    el = np.zeros((nx, ny, nz), dtype=bool)
    for a in (0, 1):
        for b in (0, 1):
            for c in (0, 1):
                el |= node_mask[a : a + nx, b : b + ny, c : c + nz]
    return el


def thin_voxels(solid: np.ndarray) -> np.ndarray:
    """Vóxeles que forman parte de una lámina o barra de 1 vóxel de grosor en algún
    eje (sus dos vecinos en ese eje están vacíos). Son frágiles y difíciles de fabricar."""
    p = np.pad(solid, 1)
    thin = np.zeros_like(solid)
    sl = slice(1, -1)
    for ax in range(3):
        lo = [sl, sl, sl]
        hi = [sl, sl, sl]
        lo[ax] = slice(0, -2)
        hi[ax] = slice(2, None)
        thin |= ~p[tuple(lo)] & ~p[tuple(hi)]
    return thin & solid


def clean_design(problem: Problem, solid: np.ndarray):
    """Elimina componentes no soportados. Devuelve (limpio, info)."""
    solid = solid & problem.domain
    lab, n = ndimage.label(solid, structure=FACE_STRUCT)
    fixed_nodes = problem.fixed.any(-1)
    fixed_el = _element_touches(fixed_nodes)
    supported_labels = np.unique(lab[fixed_el & solid])
    supported_labels = supported_labels[supported_labels > 0]
    kept = np.isin(lab, supported_labels) & solid
    return kept, {"components": int(n), "supported_components": int(len(supported_labels)),
                  "removed_voxels": int(solid.sum() - kept.sum())}


def evaluate(
    problem: Problem,
    density: np.ndarray,
    threshold: float = 0.5,
    reference_compliance: Optional[float] = None,
    target_safety_factor: float = 1.5,
) -> Evaluation:
    t0 = time.time()
    mat = problem.material
    h = problem.pitch
    solid = ((density >= threshold) & problem.domain) | problem.passive_solid
    kept, info = clean_design(problem, solid)

    checks: List[dict] = []
    metrics: Dict[str, float] = {}
    vm = np.zeros(problem.shape)
    disp = np.zeros(problem.shape)

    f_nodes = problem.forces.reshape(-1, 3)
    total_force = float(np.linalg.norm(f_nodes, axis=1).sum())
    n_kept = int(kept.sum())
    vol_mm3 = n_kept * h**3
    metrics["volume_fraction"] = n_kept / max(problem.n_domain, 1)
    metrics["volume_mm3"] = vol_mm3
    metrics["mass_g"] = vol_mm3 * mat.density / 1000.0
    metrics["removed_island_voxels"] = info["removed_voxels"]

    if n_kept == 0:
        checks.append({"name": "Camino de carga", "ok": False, "detail": "No queda material conectado a los apoyos."})
        metrics.update(compliance=float("inf"), max_displacement_mm=float("inf"), max_von_mises_MPa=float("inf"),
                       p99_von_mises_MPa=float("inf"), safety_factor=0.0, load_carried_pct=0.0)
        if reference_compliance:
            metrics.update(stiffness_retained_pct=0.0, specific_stiffness_gain=0.0)
        return Evaluation(metrics, checks, kept, vm, disp)

    # ---- 1. Camino de carga: ¿qué parte de la carga actúa sobre nodos con material?
    kept_nodes = problem.active_nodes(kept).reshape(-1)
    carried = float(np.linalg.norm(f_nodes[kept_nodes], axis=1).sum())
    carried_pct = 100.0 * carried / total_force if total_force > 0 else 100.0
    metrics["load_carried_pct"] = carried_pct
    checks.append({
        "name": "Camino de carga",
        "ok": carried_pct > 99.9,
        "detail": f"{carried_pct:.1f} % de la carga llega a los apoyos a través del material",
    })
    checks.append({
        "name": "Sin islas flotantes",
        "ok": info["removed_voxels"] == 0,
        "detail": (f"{info['components']} componente(s); eliminados {info['removed_voxels']} vóxeles sin apoyo"),
    })

    # ---- 2. FEM sobre el diseño binario
    mesh = HexMesh(kept, mat.nu, problem.fixed)
    E_el = np.full(mesh.n_elements, mat.E)
    res = mesh.solve(E_el, h, problem.forces)
    vm = mesh.von_mises(res.u, E_el, h)
    unode = np.linalg.norm(res.u, axis=-1)
    nx, ny, nz = problem.shape
    for a in (0, 1):
        for b in (0, 1):
            for c in (0, 1):
                disp += unode[a : a + nx, b : b + ny, c : c + nz] / 8
    disp *= kept
    vals = vm[kept]
    p99 = float(np.percentile(vals, 99)) if len(vals) else 0.0
    vmax = float(vals.max()) if len(vals) else 0.0
    sf = mat.yield_strength / p99 if p99 > 0 else float("inf")

    metrics["compliance_Nmm"] = res.compliance
    metrics["max_displacement_mm"] = float(unode.reshape(-1)[kept_nodes].max())
    metrics["max_von_mises_MPa"] = vmax
    metrics["p99_von_mises_MPa"] = p99
    metrics["safety_factor"] = sf
    metrics["fem_converged"] = bool(res.converged)
    if reference_compliance and res.compliance > 0 and carried_pct > 99.9:
        metrics["stiffness_retained_pct"] = 100.0 * reference_compliance / res.compliance
        # rigidez específica relativa: (k/m) / (k0/m0)
        metrics["specific_stiffness_gain"] = (reference_compliance / res.compliance) / max(metrics["volume_fraction"], 1e-9)
    elif reference_compliance:
        # si parte de la carga no llega a los apoyos, la rigidez "medida" no tiene sentido
        metrics["stiffness_retained_pct"] = 0.0
        metrics["specific_stiffness_gain"] = 0.0

    if carried_pct <= 99.9:
        # Diseño inválido: parte de la carga no llega a los apoyos. La flexibilidad
        # "medida" sería engañosamente baja (esa carga no hace trabajo), así que la
        # marcamos como infinita y el factor de seguridad como 0.
        metrics["compliance_Nmm"] = float("inf")
        metrics["max_displacement_mm"] = float("inf")
        sf = 0.0
        metrics["safety_factor"] = sf
    checks.append({
        "name": "Resistencia",
        "ok": sf >= target_safety_factor,
        "detail": f"FS = {sf:.2f} (límite {mat.yield_strength:g} MPa / σvm p99 {p99:.1f} MPa; objetivo ≥ {target_safety_factor})",
    })
    checks.append({"name": "Solución FEM", "ok": bool(res.converged),
                   "detail": "convergida" if res.converged else "el solver no convergió (¿mecanismo?)"})

    # ---- 3. Fabricabilidad: miembros de 1 vóxel
    thin_pct = 100.0 * float(thin_voxels(kept).sum()) / n_kept
    metrics["thin_member_pct"] = thin_pct
    checks.append({"name": "Espesor mínimo", "ok": thin_pct < 5.0,
                   "detail": f"{thin_pct:.1f} % del material está en miembros de 1 vóxel de grosor"})

    metrics["eval_time_s"] = time.time() - t0
    return Evaluation(metrics, checks, kept, vm, disp)


def solid_reference(problem: Problem) -> Evaluation:
    """Evalúa la pieza original maciza (100 % del dominio): la referencia."""
    return evaluate(problem, np.ones(problem.shape), threshold=0.5)
