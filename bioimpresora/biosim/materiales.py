"""Modelos físicos de la biotinta: reología, fotocurado UV y viabilidad celular.

Biotinta = biopolímero (p. ej. GelMA, alginato-metacrilado, PEGDA) mezclado con
un *primer* fotoiniciador (p. ej. LAP, Irgacure 2959) que reticula con UV.

Modelos (simplificados pero con la forma funcional de la literatura):

* Reología Herschel-Bulkley  τ = τ0 + K·γ̇ⁿ  → caudal en la boquilla.
* Cinética de fotocurado     dα/dt = k·√(I − I_inh)·(1 − α)
  con atenuación de Beer-Lambert  I(z) = I0·exp(−μ·z).
* Viabilidad celular = supervivencia a cizalla × supervivencia a dosis UV.
* Extensión (slumping) del filamento mientras no ha gelificado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Biotinta:
    nombre: str
    tau0_pa: float  # esfuerzo umbral (yield stress)
    k_pa_sn: float  # índice de consistencia K
    n: float  # índice de flujo (n < 1: pseudoplástico)
    alpha_gel: float  # conversión a la que el material gelifica
    k_cura_ref: float  # constante cinética a 0.5 % de fotoiniciador [s⁻¹ (mW/cm²)^-½]
    mu_base_mm: float  # atenuación óptica del polímero [1/mm]
    mu_pi_mm: float  # atenuación adicional por % de fotoiniciador [1/(mm·%)]
    i_inhibicion: float  # umbral por inhibición de oxígeno [mW/cm²]
    tiempo_extension_s: float  # constante de tiempo del slumping antes de gelificar
    extension_max: float  # ensanchamiento relativo máximo si nunca gelifica
    con_celulas: bool = False
    tau_critico_pa: float = 1500.0  # cizalla de referencia para daño celular
    dosis_letal_mj_cm2: float = 400.0  # dosis UV con supervivencia 1/e

    # ------------------------------------------------------------------ flujo
    def caudal_mm3_s(self, presion_kpa: float, radio_mm: float, largo_mm: float) -> float:
        """Caudal volumétrico en una boquilla cilíndrica (aprox. Herschel-Bulkley)."""
        tau_w = self.esfuerzo_pared_pa(presion_kpa, radio_mm, largo_mm)
        tau_ef = max(tau_w - self.tau0_pa, 0.0)
        if tau_ef <= 0.0:
            return 0.0
        r = radio_mm * 1e-3
        q = math.pi * self.n * r**3 / (3 * self.n + 1) * (tau_ef / self.k_pa_sn) ** (1 / self.n)
        return q * 1e9  # m³/s → mm³/s

    @staticmethod
    def esfuerzo_pared_pa(presion_kpa: float, radio_mm: float, largo_mm: float) -> float:
        return presion_kpa * 1e3 * radio_mm / (2.0 * largo_mm)

    def supervivencia_cizalla(self, presion_kpa: float, radio_mm: float, largo_mm: float) -> float:
        if not self.con_celulas:
            return 1.0
        tau_w = self.esfuerzo_pared_pa(presion_kpa, radio_mm, largo_mm)
        return float(math.exp(-0.15 * (tau_w / self.tau_critico_pa) ** 2))

    # ----------------------------------------------------------------- óptica
    def mu_mm(self, fotoiniciador_pct: float) -> float:
        return self.mu_base_mm + self.mu_pi_mm * fotoiniciador_pct

    def k_cura(self, fotoiniciador_pct: float) -> float:
        return self.k_cura_ref * math.sqrt(max(fotoiniciador_pct, 1e-6) / 0.5)

    # --------------------------------------------------------------- slumping
    def extension(self, tiempo_hasta_gel_s: np.ndarray | float) -> np.ndarray | float:
        t = np.asarray(tiempo_hasta_gel_s, dtype=float)
        t = np.where(np.isfinite(t), np.maximum(t, 0.0), 1e9)
        return self.extension_max * (1.0 - np.exp(-t / self.tiempo_extension_s))


def paso_curado(
    alpha: np.ndarray,
    k: np.ndarray,
    intensidad: np.ndarray,
    i_inh: np.ndarray,
    t_exp: np.ndarray | float,
) -> tuple[np.ndarray, np.ndarray]:
    """Aplica una exposición UV. Devuelve (alpha_nuevo, k_ef)."""
    k_ef = k * np.sqrt(np.maximum(intensidad - i_inh, 0.0))
    return 1.0 - (1.0 - alpha) * np.exp(-k_ef * t_exp), k_ef


def tiempo_hasta_conversion(alpha0, alpha_obj, k_ef):
    """Tiempo dentro de una exposición para pasar de alpha0 a alpha_obj."""
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.log((1.0 - alpha0) / (1.0 - alpha_obj)) / k_ef
    return np.where(k_ef > 0, np.maximum(t, 0.0), np.inf)


# ---------------------------------------------------------------------------
# Biblioteca de materiales por defecto
# ---------------------------------------------------------------------------

MATERIAL_A = Biotinta(
    nombre="GelMA-PEGDA estructural",
    tau0_pa=150.0, k_pa_sn=80.0, n=0.40,
    alpha_gel=0.30, k_cura_ref=0.075,
    mu_base_mm=0.3, mu_pi_mm=1.2, i_inhibicion=3.0,
    tiempo_extension_s=30.0, extension_max=0.6,
    con_celulas=False,
)

MATERIAL_B = Biotinta(
    nombre="GelMA 7% + células",
    tau0_pa=40.0, k_pa_sn=40.0, n=0.50,
    alpha_gel=0.25, k_cura_ref=0.070,
    mu_base_mm=0.5, mu_pi_mm=1.2, i_inhibicion=3.0,
    tiempo_extension_s=8.0, extension_max=0.6,
    con_celulas=True, tau_critico_pa=1500.0, dosis_letal_mj_cm2=400.0,
)

MATERIALES = {"A": MATERIAL_A, "B": MATERIAL_B}
