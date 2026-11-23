"""Simulador físico de la impresión: deposición → fotocurado → forma final y viabilidad.

Flujo:
  1. Voxeliza el órgano y planifica los 4 brazos (``planificador``).
  2. Para cada exposición UV integra la cinética de curado en todos los vóxeles
     ya depositados (Beer-Lambert a través del material superior) y acumula dosis.
  3. Con el tiempo hasta gelificar y la relación de extrusión calcula el
     ensanchamiento/aplastamiento de cada capa y reconstruye la pieza real.
  4. Compara con la geometría objetivo y calcula las métricas de calidad.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .config import Bioimpresora, ParametrosProceso
from .geometria import MAT_A, MAT_B, Geometria, generar
from .materiales import MATERIALES, Biotinta, paso_curado, tiempo_hasta_conversion
from .planificador import Plan, planificar

T_REF_S = 1200.0  # tiempo de referencia para la penalización por duración


@dataclass
class Resultado:
    metricas: dict
    geo: Geometria
    params: ParametrosProceso
    plan: Plan
    alpha: np.ndarray  # conversión final por vóxel
    dosis: np.ndarray  # dosis UV acumulada [mJ/cm²]
    viabilidad: np.ndarray  # viabilidad celular por vóxel (nan sin células)
    ocupacion_real: np.ndarray  # fracción de ocupación de la pieza impresa (z ampliado)
    objetivo: np.ndarray  # ocupación objetivo con el mismo tamaño


# ---------------------------------------------------------------------------
# utilidades geométricas
# ---------------------------------------------------------------------------

_cache_sd: dict[bytes, np.ndarray] = {}


def _borde(mask: np.ndarray) -> np.ndarray:
    p = np.pad(mask, 1, constant_values=False)
    vecino_distinto = (
        (p[1:-1, 1:-1] != p[:-2, 1:-1]) | (p[1:-1, 1:-1] != p[2:, 1:-1])
        | (p[1:-1, 1:-1] != p[1:-1, :-2]) | (p[1:-1, 1:-1] != p[1:-1, 2:])
    )
    return mask & vecino_distinto


def distancia_signada(mask: np.ndarray, res: float) -> np.ndarray:
    """Distancia (mm) al contorno: negativa dentro, positiva fuera."""
    clave = mask.tobytes() + bytes(mask.shape) + np.float64(res).tobytes()
    if clave in _cache_sd:
        return _cache_sd[clave]
    ny, nx = mask.shape
    jj, ii = np.mgrid[0:ny, 0:nx]
    pts = np.stack([jj.ravel(), ii.ravel()], 1).astype(float) * res
    sd = np.full(mask.size, 1e3)
    if mask.any() and (~mask).any():
        b_in = np.flatnonzero(_borde(mask).ravel())
        b_out = np.flatnonzero(_borde(~mask).ravel())
        dentro = mask.ravel()
        for sel, ref, signo in ((~dentro, b_in, 1.0), (dentro, b_out, -1.0)):
            idx = np.flatnonzero(sel)
            for s in range(0, idx.size, 4096):
                bloque = idx[s:s + 4096]
                d = np.sqrt(((pts[bloque, None, :] - pts[None, ref, :]) ** 2).sum(-1)).min(1)
                sd[bloque] = signo * (d - res / 2)
    elif mask.any():
        sd[:] = -1e3
    sd = sd.reshape(mask.shape)
    if len(_cache_sd) > 512:
        _cache_sd.clear()
    _cache_sd[clave] = sd
    return sd


def iou_suave(a: np.ndarray, b: np.ndarray) -> float:
    den = np.maximum(a, b).sum()
    return float(np.minimum(a, b).sum() / den) if den > 0 else 1.0


# ---------------------------------------------------------------------------


def _campo(geo: Geometria, mats: dict[str, Biotinta], f) -> np.ndarray:
    out = np.zeros(geo.forma)
    out[geo.mat == MAT_A] = f(mats["A"])
    out[geo.mat == MAT_B] = f(mats["B"])
    return out


def simular(organo: str | Geometria, params: ParametrosProceso | None = None,
            hw: Bioimpresora | None = None, materiales: dict[str, Biotinta] | None = None,
            gcode: bool = False) -> Resultado:
    p = (params or ParametrosProceso()).validar()
    hw = hw or Bioimpresora()
    mats = materiales or MATERIALES
    geo = generar(organo, altura_capa=p.altura_capa_mm) if isinstance(organo, str) else organo
    h, res = geo.altura_capa, geo.res_xy
    nz, ny, nx = geo.forma
    plan = planificar(geo, p, hw, gcode=gcode)

    ocupado = geo.mat > 0
    pi = p.fotoiniciador_pct
    k_cura = _campo(geo, mats, lambda m: m.k_cura(pi))
    mu = _campo(geo, mats, lambda m: m.mu_mm(pi))
    i_inh = _campo(geo, mats, lambda m: m.i_inhibicion)
    a_gel = _campo(geo, mats, lambda m: m.alpha_gel)
    a_gel[~ocupado] = 2.0  # nunca "gelifica" el vacío

    alpha = np.zeros(geo.forma)
    dosis = np.zeros(geo.forma)
    t_gel = np.full(geo.forma, np.inf)
    od_capa = mu * h * ocupado  # espesor óptico de cada vóxel

    # ---------------------------------------------------------------- curado
    for pas in plan.pasadas:
        L = pas.capa
        expuesta = np.isfinite(pas.t_uv)
        if not expuesta.any() or pas.t_exp <= 0:
            continue
        sub = od_capa[: L + 1]
        por_encima = np.cumsum(sub[::-1], axis=0)[::-1] - sub
        od = por_encima + 0.5 * sub
        I = pas.intensidad * np.exp(-od)
        sel = ocupado[: L + 1] & expuesta[None]
        a0 = alpha[: L + 1]
        a1, k_ef = paso_curado(a0, k_cura[: L + 1], I, i_inh[: L + 1], pas.t_exp)
        cruza = sel & (a0 < a_gel[: L + 1]) & (a1 >= a_gel[: L + 1])
        if cruza.any():
            dt = tiempo_hasta_conversion(a0, a_gel[: L + 1], k_ef)
            t_uv3 = np.broadcast_to(pas.t_uv, a0.shape)
            t_gel[: L + 1][cruza] = (t_uv3 + dt)[cruza]
        alpha[: L + 1] = np.where(sel, a1, a0)
        dosis[: L + 1] += np.where(sel, I * pas.t_exp, 0.0)

    # ------------------------------------------------------ forma resultante
    radio, largo = hw.e1.diametro_boquilla_mm / 2, hw.e1.longitud_boquilla_mm
    relacion = {}
    for clave, cfg, pres in (("A", hw.e1, p.presion_e1_kpa), ("B", hw.e2, p.presion_e2_kpa)):
        q = mats[clave].caudal_mm3_s(pres, cfg.diametro_boquilla_mm / 2, cfg.longitud_boquilla_mm)
        relacion[clave] = q / (p.velocidad_mm_s * res * h)

    ocup2d = np.zeros((nz, ny, nx))
    h_real = np.zeros(nz)
    for k in range(nz):
        alturas, pesos = [], []
        for etiqueta, clave in ((MAT_A, "A"), (MAT_B, "B")):
            m = geo.mat[k] == etiqueta
            if not m.any():
                continue
            mat = mats[clave]
            r = relacion[clave]
            espera = np.median(t_gel[k][m] - plan.t_dep[k][m])
            s = float(mat.extension(espera))
            fr_gel = float((alpha[k][m] >= mat.alpha_gel).mean())
            ancho = (r ** 0.7) * (1 + s)
            alto = (r ** 0.3) / (1 + s) * (1.0 if fr_gel >= 0.5 else 0.6)
            delta = max(ancho - 1.0, 0.0) * res / 2
            cobertura = min(ancho, 1.0)
            sd = distancia_signada(m, res)
            ocup2d[k] += np.clip(0.5 + (delta - sd) / res, 0, 1) * cobertura
            alturas.append(alto)
            pesos.append(m.sum())
        h_real[k] = h * (np.average(alturas, weights=pesos) if pesos else 1.0)
    ocup2d = np.minimum(ocup2d, 1.0)

    # proyección vertical de capas reales sobre la rejilla nominal
    z_top = np.cumsum(h_real)
    z_bot = z_top - h_real
    nz_ext = max(nz, int(math.ceil(z_top[-1] / h - 1e-9))) + 1
    lo = np.arange(nz_ext)[:, None] * h
    solape = np.clip(np.minimum(lo + h, z_top[None]) - np.maximum(lo, z_bot[None]), 0, None) / h
    ocup_real = np.minimum(np.tensordot(solape, ocup2d, axes=(1, 0)), 1.0)
    objetivo = np.zeros_like(ocup_real)
    objetivo[:nz] = ocupado

    # ----------------------------------------------------------- viabilidad
    celular = geo.mat == MAT_B
    viab = np.full(geo.forma, np.nan)
    mB = mats["B"]
    s_ciz = mB.supervivencia_cizalla(p.presion_e2_kpa, hw.e2.diametro_boquilla_mm / 2, hw.e2.longitud_boquilla_mm)
    viab[celular] = s_ciz * np.exp(-dosis[celular] / mB.dosis_letal_mj_cm2)

    # -------------------------------------------------------------- métricas
    r_spot = hw.uv.diametro_spot_mm / 2
    f_int = 1 - math.exp(-p.intensidad_uv_mw_cm2 / 20)
    if p.modo_uv == "seguimiento":
        d_lag = p.velocidad_mm_s * p.retardo_uv_s
        riesgo = f_int / (1 + math.exp((d_lag - (r_spot + 0.5)) / 0.3))
    else:
        riesgo = 0.02 * f_int

    gel = alpha >= np.where(ocupado, a_gel, 0)
    iou = iou_suave(objetivo, ocup_real)
    v_media = float(np.nanmean(viab)) if celular.any() else 1.0
    fr_curada = float(gel[ocupado].mean())
    tiempo = plan.tiempo_total_s
    puntuacion = (0.40 * iou + 0.30 * v_media + 0.15 * fr_curada
                  + 0.10 * math.exp(-tiempo / T_REF_S) + 0.05 * (1 - riesgo)
                  - (0.3 if plan.instantes_colision > 0 else 0.0))
    metricas = {
        "fidelidad_iou": iou,
        "viabilidad": v_media,
        "fraccion_curada": fr_curada,
        "conversion_media": float(alpha[ocupado].mean()),
        "error_altura": float((z_top[-1] - geo.altura_mm) / geo.altura_mm),
        "tiempo_s": float(tiempo),
        "riesgo_obstruccion": float(riesgo),
        "dosis_media_mj_cm2": float(dosis[ocupado].mean()),
        "relacion_extrusion_A": float(relacion["A"]),
        "relacion_extrusion_B": float(relacion["B"]),
        "supervivencia_cizalla": float(s_ciz),
        "espera_anticolision_s": float(plan.espera_anticolision_s),
        "instantes_colision": int(plan.instantes_colision),
        "puntuacion": float(puntuacion),
    }
    return Resultado(metricas, geo, p, plan, alpha, dosis, viab, ocup_real, objetivo)
