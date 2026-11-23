"""Planificador de trayectorias y secuenciación de los cuatro brazos.

Genera, capa a capa:
  * el raster en zig-zag de cada extrusor (0°/90° alternos entre capas),
  * el barrido o seguimiento del brazo UV,
  * la línea temporal de cada brazo (para antichoque),
  * el tiempo de deposición de cada vóxel y los instantes de exposición UV,
  * (opcional) un G-code con el dialecto de la bioimpresora.

Dialecto G-code:
  T0/T1/T2/T3  selecciona E1/E2/UV/AUX
  M700 P<kPa>  fija presión neumática      M701 / M702  abre / cierra válvula
  M710 S<mW/cm²> enciende UV               M711         apaga UV
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .cinematica import Trayectoria, distancia_minima, tiempo_viaje
from .config import Bioimpresora, ConfigBrazo, ConfigExtrusor, ParametrosProceso
from .geometria import MAT_A, MAT_B, Geometria

HERRAMIENTA = {"E1": "T0", "E2": "T1", "UV": "T2", "AUX": "T3"}


@dataclass
class PasadaUV:
    capa: int  # capa superior en el momento de la exposición
    t_uv: np.ndarray  # (ny, nx) instante en que el spot pasa sobre la columna (nan = no expuesta)
    t_exp: float  # tiempo efectivo de exposición por punto [s]
    intensidad: float  # mW/cm² en superficie


@dataclass
class Plan:
    t_dep: np.ndarray  # (nz, ny, nx) instante de deposición (nan = vacío)
    pasadas: list[PasadaUV]
    tiempo_total_s: float
    espera_anticolision_s: float = 0.0
    instantes_colision: int = 0
    holgura_min_mm: float = math.inf
    distancia_extruida_mm: dict[str, float] = field(default_factory=dict)
    gcode: list[str] | None = None
    trayectorias: dict[str, Trayectoria] = field(default_factory=dict)


# ---------------------------------------------------------------------------


def _raster(mask, xs, ys, res, transponer, invertir, v, tray: Trayectoria, cfg: ConfigBrazo, gc):
    """Raster en zig-zag de una máscara 2D. Devuelve (t_dep 2D, distancia extruida)."""
    t_dep = np.full(mask.shape, np.nan)
    M = mask.T if transponer else mask
    Td = t_dep.T if transponer else t_dep  # vista: escribir en Td escribe en t_dep
    a_coord = ys if transponer else xs  # coordenada a lo largo de la línea
    l_coord = xs if transponer else ys  # coordenada de la línea
    lineas = range(M.shape[0] - 1, -1, -1) if invertir else range(M.shape[0])
    sentido, dist = 1, 0.0

    def punto(a, l):
        return (l, a) if transponer else (a, l)

    for i in lineas:
        fila = M[i]
        if not fila.any():
            continue
        p = np.diff(np.concatenate(([0], fila.astype(np.int8), [0])))
        tramos = list(zip(np.flatnonzero(p == 1), np.flatnonzero(p == -1) - 1))
        if sentido < 0:
            tramos = [(b, a) for a, b in reversed(tramos)]
        for a, b in tramos:
            xa, xb = a_coord[a], a_coord[b]
            pa, pb = punto(xa, l_coord[i]), punto(xb, l_coord[i])
            tray.viajar(*pa, cfg.velocidad_viaje_mm_s, cfg.aceleracion_mm_s2)
            t0 = tray.fin
            idx = np.arange(min(a, b), max(a, b) + 1)
            Td[i, idx] = t0 + np.abs(a_coord[idx] - xa) / v
            largo = abs(xb - xa) + res
            tray.mover(*pb, largo / v)
            dist += largo
            if gc is not None:
                gc.append(f"G0 X{pa[0]:.3f} Y{pa[1]:.3f}")
                gc.append("M701")
                gc.append(f"G1 X{pb[0]:.3f} Y{pb[1]:.3f} F{v * 60:.0f}")
                gc.append("M702")
        sentido = -sentido
    return t_dep, dist


def _extrusor(nombre, cfg: ConfigExtrusor, mask, presion, geo, xs, ys, k, p, t_inicio, invertir, gc):
    """Plan de un extrusor en una capa, como trayectoria independiente que empieza en t_inicio."""
    tray = Trayectoria(t_inicio, cfg.posicion_reposo)
    if gc is not None and mask.any():
        gc += [f"; --- {nombre} ({cfg.rol}) ---", HERRAMIENTA[nombre], f"M700 P{presion:.1f}"]
    t_dep, dist = _raster(mask, xs, ys, geo.res_xy, k % 2 == 1, invertir,
                          p.velocidad_mm_s, tray, cfg, gc)
    tray.viajar(*cfg.posicion_reposo, cfg.velocidad_viaje_mm_s, cfg.aceleracion_mm_s2)
    return tray, t_dep, dist


def _barrido_uv(cfg, union, xs, ys, p: ParametrosProceso, tray: Trayectoria, gc):
    """Barrido UV de la capa completa. Devuelve (t_uv 2D, t_exp)."""
    ny, nx = union.shape
    t_uv = np.full((ny, nx), np.nan)
    if not union.any():
        return t_uv, 0.0
    r = cfg.diametro_spot_mm / 2
    sep = cfg.separacion_pasadas_mm
    jj, ii = np.nonzero(union)
    y0, y1 = ys[jj.min()], ys[jj.max()]
    x0, x1 = xs[ii.min()] - r, xs[ii.max()] + r
    n_filas = max(1, int(math.ceil((y1 - y0) / sep)) + 1)
    yf = (y0 + y1) / 2 + (np.arange(n_filas) - (n_filas - 1) / 2) * sep
    v = p.velocidad_uv_mm_s
    if gc is not None:
        gc += ["; --- UV (barrido por capa) ---", HERRAMIENTA["UV"]]
    # asignar cada fila de la rejilla a la pasada más cercana (dentro del spot)
    fila_de = np.argmin(np.abs(ys[:, None] - yf[None, :]), axis=1)
    cubierta = np.abs(ys - yf[fila_de]) <= max(sep / 2, r) + 1e-9
    col_ok = (xs >= x0 - 1e-9) & (xs <= x1 + 1e-9)
    for f, y in enumerate(yf):
        ini, fin = (x0, x1) if f % 2 == 0 else (x1, x0)
        tray.viajar(ini, y, cfg.velocidad_viaje_mm_s, cfg.aceleracion_mm_s2)
        t0 = tray.fin
        tray.mover(fin, y, abs(x1 - x0) / v)
        filas = np.flatnonzero((fila_de == f) & cubierta)
        t_uv[np.ix_(filas, np.flatnonzero(col_ok))] = t0 + np.abs(xs[col_ok] - ini)[None, :] / v
        if gc is not None:
            gc += [f"G0 X{ini:.3f} Y{y:.3f}", f"M710 S{p.intensidad_uv_mw_cm2:.1f}",
                   f"G1 X{fin:.3f} Y{y:.3f} F{v * 60:.0f}", "M711"]
    tray.viajar(*cfg.posicion_reposo, cfg.velocidad_viaje_mm_s, cfg.aceleracion_mm_s2)
    # tiempo efectivo de exposición = área del spot / tasa de barrido de área
    t_exp = math.pi * r * r / (v * sep)
    return t_uv, t_exp


def planificar(geo: Geometria, p: ParametrosProceso, hw: Bioimpresora | None = None,
               gcode: bool = False) -> Plan:
    hw = hw or Bioimpresora()
    p = p.validar()
    nz, ny, nx = geo.forma
    xs, ys = geo.coords_xy()
    t_dep = np.full((nz, ny, nx), np.nan)
    pasadas: list[PasadaUV] = []
    gc: list[str] | None = None
    if gcode:
        gc = [
            "; G-code generado por biosim (simulador de bioimpresora)",
            f"; organo={geo.nombre} capas={nz} modo={p.modo}",
            f"; T3 = {hw.aux.nombre}: {hw.aux.rol} -> permanece estacionado",
            "G21 ; mm", "G90 ; absoluto",
        ]
    trays = {b.nombre: Trayectoria(0.0, b.posicion_reposo) for b in hw.brazos()}
    radios = {b.nombre: b.radio_cabezal_mm for b in hw.brazos()}
    dist = {"E1": 0.0, "E2": 0.0}
    espera_total, choques, holgura = 0.0, 0, math.inf
    t = 0.0
    r_spot = hw.uv.diametro_spot_mm / 2

    for k in range(nz):
        capa = geo.mat[k]
        mA, mB = capa == MAT_A, capa == MAT_B
        z = (k + 1) * geo.altura_capa
        if gc is not None:
            gc += [f"; ===== CAPA {k} =====", f"G0 Z{z:.3f}"]

        if p.estrategia == "paralelo":
            tr1, td1, d1 = _extrusor("E1", hw.e1, mA, p.presion_e1_kpa, geo, xs, ys, k, p, t, False, gc)
            base2, td2, d2 = _extrusor("E2", hw.e2, mB, p.presion_e2_kpa, geo, xs, ys, k, p, t, True, gc)
            # buscar el menor retardo de arranque de E2 que evite colisiones
            dur1 = tr1.fin - t
            retardo, mejor = 0.0, None
            for retardo in np.arange(0.0, dur1 + 0.51, 0.5):
                tr2 = base2.desplazada(float(retardo))
                h, c = distancia_minima({"E1": tr1, "E2": tr2}, radios, t, max(tr1.fin, tr2.fin))
                if c == 0:
                    mejor = (tr2, h, c)
                    break
            if mejor is None:  # sin solución: se registra la colisión
                tr2 = base2.desplazada(float(retardo))
                h, c = distancia_minima({"E1": tr1, "E2": tr2}, radios, t, max(tr1.fin, tr2.fin))
                mejor = (tr2, h, c)
            tr2, h, c = mejor
            espera_total += float(retardo)
            choques += c
            holgura = min(holgura, h)
            td2 = td2 + float(retardo)
            trays["E1"].anexar(tr1)
            trays["E2"].anexar(tr2)
            t = max(tr1.fin, tr2.fin)
        else:
            tr1, td1, d1 = _extrusor("E1", hw.e1, mA, p.presion_e1_kpa, geo, xs, ys, k, p, t, False, gc)
            tr2, td2, d2 = _extrusor("E2", hw.e2, mB, p.presion_e2_kpa, geo, xs, ys, k, p, tr1.fin, False, gc)
            trays["E1"].anexar(tr1)
            trays["E2"].anexar(tr2)
            t = tr2.fin

        dist["E1"] += d1
        dist["E2"] += d2
        t_dep[k][mA] = td1[mA]
        t_dep[k][mB] = td2[mB]

        if p.modo_uv == "por_capa":
            tr_uv = Trayectoria(t, hw.uv.posicion_reposo)
            t_uv, t_exp = _barrido_uv(hw.uv, mA | mB, xs, ys, p, tr_uv, gc)
            trays["UV"].anexar(tr_uv)
            t = tr_uv.fin
        else:
            # El UV sigue a la boquilla a distancia v·retardo: cada punto recibe una
            # exposición total = área del spot / (v · separación de filamentos).
            t_uv = t_dep[k] + p.retardo_uv_s
            t_exp = math.pi * r_spot**2 / (p.velocidad_mm_s * geo.res_xy)
            fin_uv = np.nanmax(t_uv) if np.isfinite(t_uv).any() else t
            t = max(t, float(fin_uv) + r_spot / p.velocidad_mm_s)
            if gc is not None:
                gc.append(f"; UV en seguimiento: retardo {p.retardo_uv_s:.2f}s, {p.intensidad_uv_mw_cm2:.1f} mW/cm2")
        pasadas.append(PasadaUV(k, t_uv, t_exp, p.intensidad_uv_mw_cm2))

        t += hw.tiempo_cambio_capa_s
        for tr in trays.values():
            tr.esperar_hasta(t)

    if gc is not None:
        gc += ["; fin", "M711", "M702", "G0 Z20"]
    return Plan(t_dep, pasadas, t, espera_total, choques, holgura, dist, gc, trays)


__all__ = ["Plan", "PasadaUV", "planificar", "tiempo_viaje"]
