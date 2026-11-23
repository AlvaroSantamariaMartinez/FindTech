"""CLI de generación de datos.

    python -m toponet.nn.generate_data --n 800 --out data/dataset --workers 4

* Cada muestra se guarda en su propio .npz -> se puede interrumpir y reanudar
  (las muestras ya existentes se saltan).
* Cada proceso usa 1 hilo de BLAS para que el paralelismo sea entre muestras.
"""
from __future__ import annotations

import argparse
import os
import time

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402

import numpy as np  # noqa: E402


def _work(args):
    seed, out, shape, iters = args
    from toponet.nn.dataset import make_sample

    path = os.path.join(out, f"sample_{seed:06d}.npz")
    if os.path.exists(path):
        return seed, 0.0, "existente"
    t = time.time()
    try:
        s = make_sample(seed, shape, iters)
    except Exception as e:  # problemas degenerados: se descartan
        return seed, time.time() - t, f"error: {e}"
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **s)
    os.replace(tmp, path)
    return seed, time.time() - t, "ok"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Genera el dataset (problema -> topología SIMP)")
    ap.add_argument("--n", type=int, default=800, help="número de muestras")
    ap.add_argument("--out", default="data/dataset")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--shape", type=int, nargs=3, default=[32, 16, 16])
    ap.add_argument("--simp-iters", type=int, default=60)
    ap.add_argument("--seed0", type=int, default=0, help="semilla inicial (cambia para ampliar el dataset)")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    jobs = [(a.seed0 + i, a.out, tuple(a.shape), a.simp_iters) for i in range(a.n)]
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(_work, j) for j in jobs]
        for f in as_completed(futs):
            seed, dt, status = f.result()
            done += 1
            el = time.time() - t0
            eta = el / done * (a.n - done)
            print(f"[{done}/{a.n}] semilla {seed}: {status} ({dt:.1f}s)  transcurrido {el/60:.1f} min, ETA {eta/60:.1f} min",
                  flush=True)


if __name__ == "__main__":
    main()
