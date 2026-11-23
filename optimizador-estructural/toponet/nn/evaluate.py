"""Evaluación FÍSICA del modelo sobre el conjunto de validación.

    python -m toponet.nn.evaluate --ckpt checkpoints/toponet_unet.pt --data data/dataset --n 30

Un IoU alto no garantiza una buena estructura: una barra cortada en un único
vóxel arruina la rigidez aunque el 99 % de los píxeles coincidan. Por eso aquí
cada predicción se binariza, se analiza con FEM y se compara con la solución SIMP:

  * gap de flexibilidad   c_red / c_SIMP - 1   (0 = igual de rígida; <0 = mejor)
  * camino de carga OK    ¿llegan todas las cargas a los apoyos?
  * error de volumen
  * tiempo de inferencia vs tiempo de SIMP
  * lo mismo tras N iteraciones de refinamiento SIMP (modo híbrido)
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np

from ..analysis import evaluate
from ..simp import run_simp
from .dataset import list_samples, problem_from_sample, split_files
from .infer import predict_density
from .model import load_checkpoint


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="checkpoints/toponet_unet.pt")
    ap.add_argument("--data", default="data/dataset")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--refine", type=int, default=10, help="iteraciones SIMP del modo híbrido (0 = no)")
    ap.add_argument("--val-fraction", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None, help="JSON con los resultados")
    a = ap.parse_args(argv)

    model, ck = load_checkpoint(a.ckpt)
    files = list_samples(a.data)
    _, val = split_files(files, ck.get("args", {}).get("val_fraction", a.val_fraction), ck.get("args", {}).get("seed", a.seed))
    val = val[: a.n]
    rows = []
    for f in val:
        s = dict(np.load(f))
        p = problem_from_sample(s)
        target = s["target"].astype(float)
        ev_t = evaluate(p, target)
        t0 = time.time()
        pred = predict_density(model, p)
        t_nn = time.time() - t0
        ev_p = evaluate(p, pred)
        row = {
            "file": f,
            "t_nn_s": t_nn,
            "c_simp": ev_t.metrics["compliance_Nmm"],
            "c_nn": ev_p.metrics["compliance_Nmm"],
            "gap_nn": ev_p.metrics["compliance_Nmm"] / ev_t.metrics["compliance_Nmm"] - 1,
            "load_ok_nn": ev_p.metrics["load_carried_pct"] > 99.9,
            "vol_err_nn": abs(ev_p.metrics["volume_fraction"] - ev_t.metrics["volume_fraction"]),
        }
        if a.refine > 0:
            t0 = time.time()
            ref = run_simp(p, max_iter=a.refine, x0=pred, projection=True).density
            row["t_hybrid_s"] = t_nn + time.time() - t0
            ev_h = evaluate(p, ref)
            row["c_hybrid"] = ev_h.metrics["compliance_Nmm"]
            row["gap_hybrid"] = ev_h.metrics["compliance_Nmm"] / ev_t.metrics["compliance_Nmm"] - 1
            row["load_ok_hybrid"] = ev_h.metrics["load_carried_pct"] > 99.9
        rows.append(row)
        print(f"{f.split('/')[-1]}: gap NN {100*row['gap_nn']:+6.1f} %"
              + (f" | gap híbrido {100*row['gap_hybrid']:+6.1f} %" if a.refine > 0 else "")
              + f" | camino carga {'OK' if row['load_ok_nn'] else 'ROTO'} | {row['t_nn_s']*1000:.0f} ms", flush=True)

    def med(k):
        # los diseños con el camino de carga roto tienen gap = +inf y CUENTAN (no se filtran)
        v = [r[k] for r in rows if k in r and not np.isnan(r[k])]
        return float(np.median(v)) if v else float("nan")

    summary = {
        "n": len(rows),
        "median_gap_nn_pct": 100 * med("gap_nn"),
        "load_path_ok_nn_pct": 100 * np.mean([r["load_ok_nn"] for r in rows]),
        "median_vol_err_nn": med("vol_err_nn"),
        "median_t_nn_s": med("t_nn_s"),
    }
    if a.refine > 0:
        summary.update({
            "median_gap_hybrid_pct": 100 * med("gap_hybrid"),
            "load_path_ok_hybrid_pct": 100 * np.mean([r["load_ok_hybrid"] for r in rows]),
            "median_t_hybrid_s": med("t_hybrid_s"),
        })
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if a.out:
        with open(a.out, "w") as fh:
            json.dump({"summary": summary, "rows": rows}, fh, indent=2, ensure_ascii=False, default=float)


if __name__ == "__main__":
    main()
