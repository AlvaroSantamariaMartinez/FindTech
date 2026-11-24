"""Tu modelo: TopoNet (U-Net 3D) + refinamiento físico opcional (modo híbrido).

Flujo:
  1. rasgos del problema (incluye 1 análisis FEM de la pieza maciza)
  2. una pasada de la red  -> densidad en milisegundos
  3. calibración exacta del volumen
  4. (opcional) N iteraciones de SIMP partiendo de la predicción: corrige
     desconexiones y garantiza que el diseño es un óptimo local físico.

Detecta automáticamente todos los checkpoints `*.pt` de la carpeta `checkpoints/`
(excepto los `*_state.pt` de reanudación), así que cada modelo que entrenes
aparece en el desplegable de la WebUI.
"""
from __future__ import annotations

import glob
import os
import threading

from ..plugins import OptimizerPlugin, Param, register

def _ckpt_dirs():
    from ..paths import search_dirs

    env = os.environ.get("TOPONET_CHECKPOINTS")
    return ([env] if env else []) + search_dirs("checkpoints")


CKPT_DIR = _ckpt_dirs()[0]


def _checkpoint_paths():
    """{nombre: ruta}. Los checkpoints del usuario tienen prioridad sobre el incluido."""
    out = {}
    for d in reversed(_ckpt_dirs()):
        for f in sorted(glob.glob(os.path.join(d, "*.pt"))):
            if not f.endswith("_state.pt"):
                out[os.path.basename(f)] = f
    return out


def _checkpoints():
    return sorted(_checkpoint_paths())


@register
class NeuralUNet(OptimizerPlugin):
    id = "toponet"
    name = "TopoNet U-Net 3D (tu red)"
    kind = "neuronal / híbrido"
    description = (
        "Red neuronal convolucional 3D entrenada con soluciones SIMP. Predice la topología "
        "en una sola pasada; con 'refinamiento' > 0 actúa como híbrido: la red da el punto "
        "de partida y unas pocas iteraciones físicas garantizan la integridad."
    )

    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def available(self):
        try:
            import torch  # noqa: F401
        except Exception:
            return False, "PyTorch no está instalado (pip install torch)"
        if not _checkpoints():
            return False, f"No hay checkpoints en {CKPT_DIR}. Entrena uno: python -m toponet.nn.train"
        return True, ""

    def get_params(self):
        cks = _checkpoints() or ["(ninguno)"]
        default = "toponet_unet.pt" if "toponet_unet.pt" in cks else cks[0]
        return [
            Param("checkpoint", "choice", default, "Checkpoint", choices=cks,
                  help="Pesos entrenados (carpeta checkpoints/)."),
            Param("refine_iters", "int", 10, "Refinamiento SIMP (iter.)", min=0, max=100, step=1,
                  help="0 = solo red neuronal (instantáneo). 5-20 = híbrido (recomendado)."),
            Param("tta", "bool", False, "Test-time augmentation",
                  help="Promedia la predicción con sus espejos (4 pasadas)."),
        ]

    def _model(self, name):
        from ..nn.model import load_checkpoint

        path = _checkpoint_paths()[name]
        mtime = os.path.getmtime(path)
        with self._lock:
            hit = self._cache.get(name)
            if hit is None or hit[0] != mtime:
                model, _ck = load_checkpoint(path)
                self._cache[name] = (mtime, model)
            return self._cache[name][1]

    def optimize(self, problem, params, progress):
        from ..nn.infer import predict_density
        from ..simp import run_simp

        progress(0.05, "Calculando rasgos físicos (FEM de la pieza maciza)…")
        model = self._model(params["checkpoint"])
        progress(0.3, "Inferencia de la red…")
        rho = predict_density(model, problem, tta=params["tta"])
        n = params["refine_iters"]
        if n > 0:
            def prog(f, m):
                progress(0.35 + 0.65 * f, "Refinamiento físico: " + m)

            rho = run_simp(problem, max_iter=n, x0=rho, projection=True, progress=prog).density
        progress(1.0, "Listo")
        return rho
