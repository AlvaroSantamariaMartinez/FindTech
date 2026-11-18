"""Las venas de la diapositiva de realidad mixta: la red de vasos que MRAnalyzer traza por los surcos de un cerebro
(``mranalyzer/vasos.py``), sobre el mismo cerebro de la presentación (la resonancia pública «MRHead» de 3D Slicer).

    python3 vasos_cerebro.py ANALISIS [arteria,vena]

ANALISIS es la salida de MRAnalyzer para MRHead (``cerebro_completo.stl``). Antes hay que haber pasado
``preparar.py cerebro`` (de ``modelos/cerebro.json`` se toman el centro y la escala). Deja ``modelos/vasos.json`` y
``modelos/vasos.bin``: los vasos hechos tubos, con la distancia de cada vértice a la raíz de su árbol medida por los vasos
(con ella se dibujan creciendo desde la raíz). La red es generada, no sale de la resonancia: una T1 no ve estos vasos.
"""
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from scipy import sparse
from scipy.sparse import csgraph
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "mranalyzer"))
from mranalyzer import vasos  # noqa: E402

AQUI = Path(__file__).resolve().parent.parent
LADOS = 5
GROSOR = (1.7, 0.75)  # (para que se vean desde lejos: radio × 1,7, y nunca menos de 0,75 mm)
PASO_MM = 1.4       # (un anillo cada tanto: el tubo se ve igual de liso y pesa mucho menos)
UNION_MM = 1.5      # (un extremo de rama a menos de esto de otra rama está unido a ella)

analisis = Path(sys.argv[1])
tipos = tuple(sys.argv[2].split(",")) if len(sys.argv) > 2 else ("vena",)
cerebro = json.loads((AQUI / "modelos" / "cerebro.json").read_text(encoding="utf-8"))
centro, escala = np.asarray(cerebro["centro_mm"], float), float(cerebro["escala"])

red = vasos.generar(trimesh.load(analisis / "cerebro_completo.stl", force="mesh"), densidad="pocos", semilla=3, tipos=tipos)


def remuestrear(r):
    """La rama con un punto cada PASO_MM (los extremos, donde se une a las demás, se quedan)."""
    p = r["puntos"]
    s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
    if s[-1] < 1e-6:
        return None
    k = np.linspace(0, s[-1], max(2, int(round(s[-1] / PASO_MM)) + 1))
    n = np.stack([np.interp(k, s, r["normales"][:, j]) for j in range(3)], 1)
    return {**r, "puntos": np.stack([np.interp(k, s, p[:, j]) for j in range(3)], 1), "radios": np.interp(k, s, r["radios"]),
            "normales": n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)}


# (sin las ramitas finas: a la distancia de la diapositiva no se ven y son la mitad de la red)
ramas = [x for x in (remuestrear(r) for r in red.ramas if not r.get("fina") and len(r["puntos"]) > 1) if x is not None]
print(len(ramas), "ramas,", round(sum(np.linalg.norm(np.diff(r["puntos"], axis=0), axis=1).sum() for r in ramas) / 1000, 2), "m")

# La distancia a la raíz, por los vasos: un grafo con todos los puntos (seguidos dentro de cada rama, y cada extremo de
# rama unido al punto más cercano de otra), y Dijkstra desde el punto más grueso de cada árbol (su tronco).
puntos = np.concatenate([r["puntos"] for r in ramas])
radios = np.concatenate([r["radios"] for r in ramas])
de_rama = np.concatenate([np.full(len(r["puntos"]), i) for i, r in enumerate(ramas)])
inicio = np.cumsum([0] + [len(r["puntos"]) for r in ramas])
filas, columnas, pesos = [], [], []
for i, r in enumerate(ramas):
    a = np.arange(inicio[i], inicio[i + 1] - 1)
    filas += a.tolist(); columnas += (a + 1).tolist()
    pesos += np.linalg.norm(np.diff(r["puntos"], axis=0), axis=1).tolist()
arbol = cKDTree(puntos)
for i in range(len(ramas)):
    for extremo in (inicio[i], inicio[i + 1] - 1):
        cerca = [j for j in arbol.query_ball_point(puntos[extremo], UNION_MM) if de_rama[j] != i]
        if cerca:
            j = min(cerca, key=lambda j: np.linalg.norm(puntos[j] - puntos[extremo]))
            filas.append(extremo); columnas.append(j); pesos.append(max(float(np.linalg.norm(puntos[j] - puntos[extremo])), 1e-3))
g = sparse.coo_matrix((pesos, (filas, columnas)), shape=(len(puntos), len(puntos))).tocsr()
n, componente = csgraph.connected_components(g, directed=False)
raices = [int(np.flatnonzero(componente == c)[np.argmax(radios[componente == c])]) for c in range(n)]
largo = csgraph.dijkstra(g, directed=False, indices=raices, min_only=True)
print(n, "árboles; el vaso más largo,", round(float(largo.max())), "mm")

# Los tubos: un anillo por punto, en el plano perpendicular a la rama, un poco hundido en la superficie.
vs, ls, caras = [], [], []
for i, r in enumerate(ramas):
    p, nr = r["puntos"], r["normales"]
    rad = np.maximum(r["radios"] * GROSOR[0], GROSOR[1])
    t = np.gradient(p, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    b = np.cross(t, nr)
    b /= np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-9)
    n2 = np.cross(b, t)
    c = p + nr * rad[:, None] * 0.55
    ang = np.arange(LADOS) / LADOS * 2 * np.pi
    anillos = c[:, None] + rad[:, None, None] * (np.cos(ang)[None, :, None] * n2[:, None] + np.sin(ang)[None, :, None] * b[:, None])
    base = sum(len(x) for x in vs)
    vs.append(anillos.reshape(-1, 3))
    ls.append(np.repeat(largo[inicio[i]:inicio[i + 1]], LADOS))
    for k in range(len(p) - 1):
        for s in range(LADOS):
            a0, a1 = base + k * LADOS + s, base + k * LADOS + (s + 1) % LADOS
            b0, b1 = a0 + LADOS, a1 + LADOS
            caras += [a0, b0, a1, a1, b0, b1]
v = (np.concatenate(vs) - centro) * escala
pos = np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1)      # (como el cerebro: el eje vertical del paciente hacia arriba)
lo, tam = pos.min(0), np.maximum(np.ptp(pos, axis=0), 1e-9)
q = np.round((pos - lo) / tam * 65535).astype(np.uint16)
largos = np.concatenate(ls)
maximo = float(largos.max())
ql = np.round(largos / maximo * 65535).astype(np.uint16)
idx = np.asarray(caras, np.uint32)
(AQUI / "modelos" / "vasos.bin").write_bytes(q.tobytes() + ql.tobytes() + idx.tobytes())
(AQUI / "modelos" / "vasos.json").write_text(json.dumps({
    "tipos": list(tipos), "vertices": int(len(q)), "indices": int(len(idx)), "largo_max_mm": round(maximo, 2),
    "min": [round(float(x), 5) for x in lo], "tam": [round(float(x), 5) for x in tam],
    "pos": [0, len(q)], "largo": [q.nbytes, len(ql)], "idx": [q.nbytes + ql.nbytes, len(idx)]}), encoding="utf-8")
print(len(q), "vértices,", len(idx) // 3, "caras,", (q.nbytes + ql.nbytes + idx.nbytes) // 1024, "KB")
