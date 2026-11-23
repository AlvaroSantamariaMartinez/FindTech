"""Red neuronal profunda (perceptrón multicapa) implementada en NumPy puro.

Incluye retropropagación, optimizador Adam, regularización L2, mini-lotes,
parada temprana y el gradiente respecto a la *entrada* (necesario para el
diseño inverso de parámetros de impresión).
"""

from __future__ import annotations

import numpy as np


def _act(nombre: str):
    if nombre == "silu":
        def f(z):
            s = 1 / (1 + np.exp(-z))
            return z * s, s * (1 + z * (1 - s))
    elif nombre == "tanh":
        def f(z):
            a = np.tanh(z)
            return a, 1 - a * a
    elif nombre == "relu":
        def f(z):
            return np.maximum(z, 0), (z > 0).astype(z.dtype)
    else:
        raise ValueError(nombre)
    return f


class RedNeuronal:
    def __init__(self, capas: list[int], activacion: str = "silu", semilla: int = 0):
        rng = np.random.default_rng(semilla)
        self.capas = list(capas)
        self.activacion = activacion
        self._f = _act(activacion)
        self.W = [rng.normal(0, np.sqrt(2 / a), (a, b)) for a, b in zip(capas[:-1], capas[1:])]
        self.b = [np.zeros(b) for b in capas[1:]]

    # ----------------------------------------------------------- propagación
    def adelante(self, X: np.ndarray):
        cache = []
        a = X
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            z = a @ W + b
            if i < len(self.W) - 1:
                a_sig, d = self._f(z)
                cache.append((a, d))
                a = a_sig
            else:
                cache.append((a, None))
                a = z
        return a, cache

    def atras(self, dY: np.ndarray, cache):
        gW, gb = [None] * len(self.W), [None] * len(self.b)
        g = dY
        for i in range(len(self.W) - 1, -1, -1):
            a_prev, _ = cache[i]
            gW[i] = a_prev.T @ g
            gb[i] = g.sum(0)
            g = g @ self.W[i].T
            if i > 0:
                g = g * cache[i - 1][1]
        return gW, gb, g  # g = dL/dX

    def predecir(self, X: np.ndarray) -> np.ndarray:
        return self.adelante(X)[0]

    def gradiente_entrada(self, X: np.ndarray, pesos_salida: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Devuelve (y, d(y·pesos)/dX) para cada fila de X."""
        y, cache = self.adelante(X)
        _, _, gX = self.atras(np.broadcast_to(pesos_salida, y.shape).copy(), cache)
        return y, gX

    # ---------------------------------------------------------- entrenamiento
    def entrenar(self, X, Y, Xv, Yv, epocas=400, lote=64, lr=2e-3, l2=1e-5,
                 paciencia=40, semilla=0, verbose=True, pesos_salida=None):
        rng = np.random.default_rng(semilla)
        w_out = np.ones(Y.shape[1]) if pesos_salida is None else np.asarray(pesos_salida)
        params = self.W + self.b
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        b1, b2, eps, paso = 0.9, 0.999, 1e-8, 0
        mejor, mejor_estado, sin_mejora = np.inf, None, 0
        historia = []
        n = len(X)
        for ep in range(epocas):
            lr_ep = lr * 0.5 * (1 + np.cos(np.pi * ep / epocas))  # cosine decay
            perm = rng.permutation(n)
            perdida_ep = 0.0
            for s in range(0, n, lote):
                idx = perm[s:s + lote]
                pred, cache = self.adelante(X[idx])
                err = (pred - Y[idx]) * w_out
                perdida_ep += float((err * (pred - Y[idx])).sum())
                gW, gb, _ = self.atras(2 * err / len(idx), cache)
                grads = [g + l2 * W for g, W in zip(gW, self.W)] + gb
                paso += 1
                for k, (p, g) in enumerate(zip(params, grads)):
                    m[k] = b1 * m[k] + (1 - b1) * g
                    v[k] = b2 * v[k] + (1 - b2) * g * g
                    p -= lr_ep * (m[k] / (1 - b1**paso)) / (np.sqrt(v[k] / (1 - b2**paso)) + eps)
            val = float((((self.predecir(Xv) - Yv) ** 2) * w_out).mean())
            historia.append((perdida_ep / (n * Y.shape[1]), val))
            if val < mejor - 1e-6:
                mejor, sin_mejora = val, 0
                mejor_estado = ([W.copy() for W in self.W], [b.copy() for b in self.b])
            else:
                sin_mejora += 1
            if verbose and (ep % 25 == 0 or ep == epocas - 1):
                print(f"  época {ep:4d}  pérdida_ent={historia[-1][0]:.4f}  pérdida_val={val:.4f}")
            if sin_mejora >= paciencia:
                if verbose:
                    print(f"  parada temprana en época {ep} (mejor val={mejor:.4f})")
                break
        if mejor_estado:
            self.W, self.b = mejor_estado
        return historia

    # ---------------------------------------------------------- persistencia
    def estado(self) -> dict:
        d = {"capas": np.array(self.capas), "activacion": np.array(self.activacion)}
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            d[f"W{i}"], d[f"b{i}"] = W, b
        return d

    @classmethod
    def desde_estado(cls, d) -> "RedNeuronal":
        red = cls([int(c) for c in d["capas"]], str(d["activacion"]))
        red.W = [d[f"W{i}"] for i in range(len(red.W))]
        red.b = [d[f"b{i}"] for i in range(len(red.b))]
        return red
