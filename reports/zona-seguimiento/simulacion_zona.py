"""Simulación geométrica de la «zona de seguimiento»: qué ganan 2, 3 o 4 cámaras fijas frente a la cámara de las gafas
cuando una mano sujeta la pieza. No usa datos de pacientes: la pieza es una forma de huevo de 184 × 136 × 135 mm, como
el cerebro de silicona de prueba. Lo que calcula:

  1. Qué parte del contorno de la pieza le queda útil a cada cámara (ni tapada por la mano ni con la mano de fondo).
  2. Con qué precisión queda determinada la pose con ese contorno (cota de Cramér-Rao: cada punto útil del contorno
     mide un desplazamiento en la imagen, perpendicular al contorno, con un ruido en píxeles).

El ruido se ajusta para que una sola cámara sin mano dé 1 mm, que es lo que midió el seguidor en el banco sintético
del proyecto (DISENO-realidad-mixta.md). Las cifras absolutas son orientativas; lo que vale es la proporción.

Uso: python simulacion_zona.py salida.json
"""
import json
import sys

import numpy as np
import trimesh
from scipy.spatial import cKDTree

RNG = np.random.default_rng(20261113)
N = 4000  # (agarres simulados)

# ---- La pieza (m). x: de atrás a delante; y: ancho; z: alto. --------------------------------------------------------
A, B, C_ARRIBA, C_ABAJO = 0.092, 0.068, 0.080, 0.055


def forma(d):
    """De la esfera unidad a la superficie de la pieza: más estrecha por delante y más plana por abajo."""
    d = np.atleast_2d(d)
    x, y, z = d[:, 0], d[:, 1], d[:, 2]
    return np.stack([A * x, B * y * (1 - 0.15 * x) / 1.15, np.where(z > 0, C_ARRIBA, C_ABAJO) * z], 1)


_esfera = trimesh.creation.icosphere(subdivisions=5)
MALLA = trimesh.Trimesh(forma(_esfera.vertices), _esfera.faces, process=False)
MALLA.fix_normals()
PUNTOS = np.asarray(MALLA.vertices)
NORMALES = np.asarray(MALLA.vertex_normals)
ARBOL = cKDTree(PUNTOS)

# ---- La zona (m). Mesa en z = 0; quien mira está en −y. -------------------------------------------------------------
CENTRO = np.array([0.0, 0.0, 0.22])
ESQUINAS = np.array([[-0.30, 0.30, 0.56], [0.30, 0.30, 0.56], [-0.30, -0.30, 0.56], [0.30, -0.30, 0.56]])
# (cámara Global Shutter de 1456 × 1088 con lente de 6 mm, tratada a media resolución)
FIJA = dict(fx=6.0 / 0.00345 / 2, ancho=728, alto=544)
# (la cámara de las gafas a la resolución del seguidor: 640 × 480)
GAFAS = dict(fx=370.0, ancho=640, alto=480)
CONFIG = {"Gafas (ahora)": ["g"], "2 cámaras fijas": [0, 1], "3 cámaras fijas": [0, 1, 2], "4 cámaras fijas": [0, 1, 2, 3]}
PREVIA = np.diag([1 / 0.03**2] * 3 + [1 / np.radians(20) ** 2] * 3)  # (más allá de 30 mm o 20°, perdida)
CONTORNO_MEDIDAS = 200  # (medidas independientes de un contorno entero)


def unidad(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def giro_al_azar():
    q = unidad(RNG.normal(size=4))
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def mirar(desde, hacia):
    """Los ejes de una cámara (filas: derecha, abajo, adelante) que mira de «desde» a «hacia»."""
    f = unidad(hacia - desde)
    arriba = np.array([0.0, 0.0, 1.0])
    r = unidad(np.cross(f, arriba))
    return np.stack([r, np.cross(f, r), f])


def mano(pos, giro, lado):
    """Las cápsulas (inicio, fin, radio) de una mano que sujeta la pieza, con su antebrazo. lado: +1 derecha."""
    hombro = np.array([0.18 * lado, -0.50, 0.35]) + RNG.normal(0, 0.03, 3)
    tipo = RNG.choice(3, p=[0.55, 0.30, 0.15])
    lateral = np.array([lado, 0.0, 0.0])
    if tipo == 0:    # (por debajo, la palma hacia arriba)
        g = np.array([0, 0, -1.0]) + 0.5 * RNG.normal(0, 0.5) * lateral + np.array([0, -0.4, 0]) * RNG.uniform()
    elif tipo == 1:  # (por el costado)
        g = lateral + np.array([0, -0.7, 0]) * RNG.uniform() + np.array([0, 0, -0.5]) * RNG.uniform()
    else:            # (por encima)
        g = np.array([0, 0, 1.0]) + np.array([0, -0.6, 0]) * RNG.uniform() + RNG.normal(0, 0.3) * lateral
    g = unidad(g)
    f = unidad(pos + 0.08 * g - hombro)   # (del hombro a la palma: los dedos siguen en ese sentido)
    t = f - f.dot(g) * g
    t = unidad(t if np.linalg.norm(t) > 1e-3 else np.cross(g, [1.0, 0, 0]))
    s = np.cross(g, t) * lado

    def sobre(theta, phi, fuera):
        th, ph = np.radians(theta), np.radians(phi)
        d = unidad(np.cos(th) * np.cos(ph) * g + np.sin(th) * np.cos(ph) * t + np.sin(ph) * s)
        local = forma(giro.T @ d)[0]
        n = NORMALES[ARBOL.query(local)[1]]
        return pos + giro @ (local + fuera * n)

    capsulas = []
    for phi in (-24, -8, 8, 24):      # (cuatro dedos)
        pts = [sobre(th, phi, 0.009) for th in np.linspace(28, 100, 6)]
        capsulas += [(a, b, 0.009) for a, b in zip(pts[:-1], pts[1:])]
    pts = [sobre(th, ph, 0.011) for th, ph in zip(np.linspace(-10, 20, 4), np.linspace(40, 95, 4))]  # (pulgar)
    capsulas += [(a, b, 0.011) for a, b in zip(pts[:-1], pts[1:])]
    for phi in (-20, 0, 20):          # (palma)
        pts = [sobre(th, phi, 0.014) for th in np.linspace(-40, 30, 5)]
        capsulas += [(a, b, 0.014) for a, b in zip(pts[:-1], pts[1:])]
    talon = sobre(-45, 0, 0.035)
    capsulas.append((talon, talon + 0.26 * unidad(hombro - talon), 0.030))  # (antebrazo)
    return capsulas


def tapa(camara, puntos, capsulas):
    """Qué puntos no sirven: la recta de la cámara al punto, alargada por detrás, pasa por alguna cápsula."""
    if not capsulas:
        return np.zeros(len(puntos), bool)
    p1 = np.broadcast_to(camara, puntos.shape)[:, None, :]
    d1 = (puntos + 0.25 * unidad(puntos - camara) - camara)[:, None, :]
    p2 = np.array([c[0] for c in capsulas])[None]
    d2 = np.array([c[1] - c[0] for c in capsulas])[None]
    radios = np.array([c[2] for c in capsulas])[None]
    r = p1 - p2
    a = (d1 * d1).sum(-1); e = (d2 * d2).sum(-1); f = (d2 * r).sum(-1)
    b = (d1 * d2).sum(-1); c = (d1 * r).sum(-1)
    den = a * e - b * b
    s = np.clip(np.where(den > 1e-12, (b * f - c * e) / np.maximum(den, 1e-12), 0.0), 0, 1)
    t = np.clip((b * s + f) / e, 0, 1)
    s = np.clip((b * t - c) / a, 0, 1)
    dist = np.linalg.norm(r + d1 * s[..., None] - d2 * t[..., None], axis=-1)
    return (dist < radios).any(1)


def vista(camara, ejes, optica, pos, giro, capsulas, ruido):
    """El contorno que ve una cámara: (parte útil, información de la pose 6 × 6)."""
    mundo = pos + PUNTOS @ giro.T
    normales = NORMALES @ giro.T
    rayo = unidad(mundo - camara)
    borde = np.abs((normales * rayo).sum(1)) < 0.04
    X, n = mundo[borde], normales[borde]
    xc = (X - camara) @ ejes.T
    u = optica["fx"] * xc[:, 0] / xc[:, 2] + optica["ancho"] / 2
    v = optica["fx"] * xc[:, 1] / xc[:, 2] + optica["alto"] / 2
    dentro = (xc[:, 2] > 0.05) & (u > 2) & (u < optica["ancho"] - 2) & (v > 2) & (v < optica["alto"] - 2)
    util = dentro & ~tapa(camara, X, capsulas)
    if not util.any():
        return 0.0, np.zeros((6, 6))
    Xu, xcu = X[util], xc[util]
    nc = n[util] @ ejes.T
    z = xcu[:, 2]
    # (la proyección: du = fx (dx − x dz / z) / z; el contorno se mide en la dirección de su normal en la imagen)
    Jp = np.zeros((len(Xu), 2, 3))
    Jp[:, 0, 0] = optica["fx"] / z; Jp[:, 0, 2] = -optica["fx"] * xcu[:, 0] / z**2
    Jp[:, 1, 1] = optica["fx"] / z; Jp[:, 1, 2] = -optica["fx"] * xcu[:, 1] / z**2
    nu = unidad(np.einsum("nij,nj->ni", Jp, nc))
    fila_c = np.einsum("ni,nij->nj", nu, Jp)          # (por metro, en ejes de la cámara)
    fila = fila_c @ ejes                               # (en el mundo)
    brazo = Xu - pos
    J = np.concatenate([fila, np.cross(brazo, fila)], 1)  # (traslación y giro alrededor del centro de la pieza)
    peso = CONTORNO_MEDIDAS / borde.sum() / ruido**2
    return util.sum() / borde.sum(), peso * J.T @ J


def agarre(con_mano):
    pos = CENTRO + np.array([RNG.uniform(-0.10, 0.10), RNG.uniform(-0.10, 0.10), RNG.uniform(-0.08, 0.08)])
    giro = giro_al_azar()
    capsulas = []
    if con_mano:
        lado = RNG.choice([-1, 1])
        capsulas += mano(pos, giro, lado)
        if RNG.uniform() < 0.35:
            capsulas += mano(pos, giro, -lado)
    az, el, d = RNG.normal(0, np.radians(20)), np.radians(RNG.uniform(20, 55)), RNG.uniform(0.35, 0.55)
    ojo = pos + d * np.array([np.sin(az) * np.cos(el), -np.cos(az) * np.cos(el), np.sin(el)])
    return pos, giro, capsulas, ojo


def medir(ruido, con_mano, n):
    """Para cada agarre y cada cámara: la parte útil del contorno y la información; y los ejes de las gafas."""
    salida = []
    for _ in range(n):
        pos, giro, capsulas, ojo = agarre(con_mano)
        ejes_ojo = mirar(ojo, pos)
        por_camara = {"g": vista(ojo, ejes_ojo, GAFAS, pos, giro, capsulas, ruido)}
        for i, c in enumerate(ESQUINAS):
            por_camara[i] = vista(c, mirar(c, CENTRO), FIJA, pos, giro, capsulas, ruido)
        salida.append((por_camara, ejes_ojo))
    return salida


def precision(agarres, camaras):
    """Error (1 sigma) visto desde las gafas: de lado, en profundidad, total (mm) y de giro (°)."""
    filas = []
    for por_camara, ejes in agarres:
        info = PREVIA + sum(por_camara[c][1] for c in camaras)
        cov = np.linalg.inv(info)
        ct = ejes @ cov[:3, :3] @ ejes.T
        filas.append([1e3 * np.sqrt(ct[0, 0] + ct[1, 1]), 1e3 * np.sqrt(ct[2, 2]), 1e3 * np.sqrt(np.trace(ct)),
                      np.degrees(np.sqrt(np.trace(cov[3:, 3:])))])
    return np.array(filas)


def main(destino):
    global RNG
    # 1. El ruido que da 1 mm con una cámara y sin mano (el banco sintético del proyecto).
    ruido = 1.0
    for _ in range(6):
        RNG = np.random.default_rng(1)
        total = np.median(precision(medir(ruido, False, 400), ["g"])[:, 2])
        ruido /= total
    resultado = {"agarres": N, "ruido_px": round(ruido, 3), "escenarios": {}}
    for nombre, con_mano in (("sin mano", False), ("con mano", True)):
        RNG = np.random.default_rng(20261113)
        agarres = medir(ruido, con_mano, N)
        esc = {"precision": {}, "contorno": {}}
        for config, camaras in CONFIG.items():
            p = precision(agarres, camaras)
            esc["precision"][config] = {k: {"mediana": round(float(np.median(p[:, i])), 2),
                                             "p95": round(float(np.percentile(p[:, i], 95)), 2)}
                                        for i, k in enumerate(("lado_mm", "fondo_mm", "total_mm", "giro_grados"))}
            esc["precision"][config]["dentro_de_2mm"] = round(float((p[:, 2] <= 2).mean() * 100), 1)
            esc["precision"][config]["dentro_de_5mm"] = round(float((p[:, 2] <= 5).mean() * 100), 1)
            mejor = np.array([max(pc[c][0] for c in camaras) for pc, _ in agarres])
            esc["contorno"][config] = [round(float((mejor >= u / 100).mean() * 100), 1) for u in range(0, 101, 5)]
        resultado["escenarios"][nombre] = esc
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=1)
    print(json.dumps(resultado, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
