"""Interfaz de línea de comandos:  python -m biosim <comando> ..."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import fields

import numpy as np

from .config import Bioimpresora, ParametrosProceso
from .geometria import ORGANOS, ascii_capa, generar
from .materiales import MATERIALES
from .simulador import simular


def _params(a) -> ParametrosProceso:
    vals = {f.name: getattr(a, f.name) for f in fields(ParametrosProceso) if getattr(a, f.name, None) is not None}
    return ParametrosProceso(**vals)


def _args_params(sp):
    g = sp.add_argument_group("parámetros de proceso")
    for f in fields(ParametrosProceso):
        tipo = str if f.name in ("modo_uv", "estrategia") else float
        g.add_argument(f"--{f.name.replace('_', '-')}", dest=f.name, type=tipo, default=None,
                       help=f"(defecto {f.default})")


def _tabla(metricas: dict) -> str:
    return "\n".join(f"  {k:<24} {v:>10.4f}" if isinstance(v, float) else f"  {k:<24} {v:>10}"
                     for k, v in metricas.items())


def cmd_info(a):
    hw = Bioimpresora()
    print("BIOIMPRESORA – configuración de brazos")
    for b in hw.brazos():
        estado = "activo" if b.activo else "INACTIVO"
        print(f"  {b.nombre:<4} [{b.tipo:<9}] {estado:<8} reposo={b.posicion_reposo}  {b.rol}")
    print("\nMateriales:")
    for k, m in MATERIALES.items():
        print(f"  {k}: {m.nombre}  τ0={m.tau0_pa} Pa  K={m.k_pa_sn} Pa·sⁿ  n={m.n}  "
              f"α_gel={m.alpha_gel}  células={'sí' if m.con_celulas else 'no'}")
    print("\nÓrganos disponibles:", ", ".join(ORGANOS))


def cmd_simular(a):
    p = _params(a)
    t = time.time()
    r = simular(a.organo, p, gcode=bool(a.gcode))
    print(f"Simulación '{a.organo}' modo={p.validar().modo}  ({(time.time() - t) * 1000:.0f} ms)")
    print(_tabla(r.metricas))
    if a.ver_capa is not None:
        k = min(a.ver_capa, r.geo.forma[0] - 1)
        print(f"\nCapa objetivo {k}  (█ = A estructural, ▒ = B celular):")
        print(ascii_capa(r.geo.mat[k]))
    if a.gcode:
        with open(a.gcode, "w") as fh:
            fh.write("\n".join(r.plan.gcode) + "\n")
        print(f"\nG-code guardado en {a.gcode} ({len(r.plan.gcode)} líneas)")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"parametros": p.a_dict(), "metricas": r.metricas}, fh, indent=2, ensure_ascii=False)


def cmd_dataset(a):
    from .ia.datos import generar_dataset, guardar_dataset
    print(f"Generando {a.n} simulaciones...")
    t = time.time()
    X, Y = generar_dataset(a.n, semilla=a.semilla, organo=a.organo, procesos=a.procesos)
    guardar_dataset(a.salida, X, Y)
    print(f"Dataset {X.shape} → {Y.shape} guardado en {a.salida} ({time.time() - t:.1f} s)")


def cmd_entrenar(a):
    from .ia.datos import cargar_dataset
    from .ia.sustituto import ModeloSustituto
    X, Y = cargar_dataset(a.datos)
    ocultas = tuple(int(c) for c in a.capas.split(","))
    print(f"Entrenando red {X.shape[1]}→{'→'.join(map(str, ocultas))}→{Y.shape[1]} con {len(X)} muestras")
    modelo, ev, _ = ModeloSustituto.entrenar(X, Y, ocultas=ocultas, epocas=a.epocas, lr=a.lr, semilla=a.semilla)
    modelo.guardar(a.modelo)
    print("\nValidación (datos no vistos):")
    for k, v in ev.items():
        print(f"  {k:<20} R²={v['R2']:.3f}  MAE={v['MAE']:.4f}")
    print(f"\nModelo guardado en {a.modelo}")


def cmd_optimizar(a):
    from .ia.sustituto import ModeloSustituto
    modelo = ModeloSustituto.cargar(a.modelo)
    t = time.time()
    res = modelo.optimizar(a.organo, n_inicios=a.inicios, pasos=a.pasos,
                           viab_min=a.viabilidad_min, iou_min=a.fidelidad_min, semilla=a.semilla)
    base = simular(a.organo, ParametrosProceso())
    mejor = res[0]
    print(f"Diseño inverso para '{a.organo}' ({time.time() - t:.1f} s)\n")
    print("Parámetros óptimos:")
    for k, v in mejor.params.a_dict().items():
        print(f"  {k:<24} {v:.3f}" if isinstance(v, float) else f"  {k:<24} {v}")
    print(f"\n  {'métrica':<22} {'base':>9} {'predicha':>9} {'simulada':>9}")
    for k in ("fidelidad_iou", "viabilidad", "fraccion_curada", "error_altura", "riesgo_obstruccion", "puntuacion"):
        print(f"  {k:<22} {base.metricas[k]:9.3f} {mejor.prediccion.get(k, float('nan')):9.3f} "
              f"{mejor.metricas_simuladas[k]:9.3f}")
    print(f"  {'tiempo_s':<22} {base.metricas['tiempo_s']:9.0f} "
          f"{10 ** mejor.prediccion['log10_tiempo']:9.0f} {mejor.metricas_simuladas['tiempo_s']:9.0f}")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"parametros": mejor.params.a_dict(), "metricas": mejor.metricas_simuladas}, fh,
                      indent=2, ensure_ascii=False)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="biosim", description="Simulador y aprendizaje profundo para bioimpresora de órganos")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="Muestra la configuración de la máquina")

    sp = sub.add_parser("simular", help="Simula una impresión")
    sp.add_argument("--organo", default="vaso", choices=list(ORGANOS))
    sp.add_argument("--ver-capa", type=int, default=None)
    sp.add_argument("--gcode", default=None, help="ruta para guardar el G-code")
    sp.add_argument("--json", default=None)
    _args_params(sp)

    sp = sub.add_parser("dataset", help="Genera datos de entrenamiento con el simulador")
    sp.add_argument("--n", type=int, default=2000)
    sp.add_argument("--salida", default="datos.npz")
    sp.add_argument("--organo", default=None, choices=list(ORGANOS))
    sp.add_argument("--semilla", type=int, default=0)
    sp.add_argument("--procesos", type=int, default=None)

    sp = sub.add_parser("entrenar", help="Entrena la red neuronal sustituta")
    sp.add_argument("--datos", default="datos.npz")
    sp.add_argument("--modelo", default="modelo.npz")
    sp.add_argument("--capas", default="128,128,64")
    sp.add_argument("--epocas", type=int, default=400)
    sp.add_argument("--lr", type=float, default=2e-3)
    sp.add_argument("--semilla", type=int, default=0)

    sp = sub.add_parser("optimizar", help="Busca los parámetros óptimos con la red (diseño inverso)")
    sp.add_argument("--modelo", default="modelo.npz")
    sp.add_argument("--organo", default="vaso", choices=list(ORGANOS))
    sp.add_argument("--inicios", type=int, default=64)
    sp.add_argument("--pasos", type=int, default=200)
    sp.add_argument("--viabilidad-min", type=float, default=None)
    sp.add_argument("--fidelidad-min", type=float, default=None)
    sp.add_argument("--semilla", type=int, default=0)
    sp.add_argument("--json", default=None)

    a = ap.parse_args(argv)
    np.set_printoptions(precision=4, suppress=True)
    {"info": cmd_info, "simular": cmd_simular, "dataset": cmd_dataset,
     "entrenar": cmd_entrenar, "optimizar": cmd_optimizar}[a.cmd](a)


if __name__ == "__main__":
    main()
