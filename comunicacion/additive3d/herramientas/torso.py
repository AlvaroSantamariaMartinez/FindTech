"""El torso de las diapositivas de la red neuronal, la simulación y la realidad mixta. Sale del TAC de tórax público
«CTChest» de las muestras de 3D Slicer, segmentado con TotalSegmentator. No es un paciente.

    TotalSegmentator -i ct.nii.gz -o seg.nii.gz --ml
    python3 torso.py ct.nii.gz seg.nii.gz

Deja en ``modelos/``:
- ``torso.json`` / ``torso.bin``: el torso entero (la piel) y sus estructuras, con las posiciones y los índices en 16
  bits, como ``cerebro.json`` (las estructuras de la capa 2 son las que se ven por dentro).
- ``vasos.json`` / ``vasos.bin``: los vasos grandes del tórax, con la distancia de cada vértice al corazón medida por el
  propio vaso (con ella se dibujan creciendo desde el corazón en la realidad mixta).

y en ``img/`` los 14 cortes de la simulación (``corte_NN.webp``) y el corte de la diapositiva de la red neuronal con su
segmentación (``red_entrada.webp`` y ``red_salida.png``).

Ejes de la escena: x hacia la izquierda del paciente, y hacia arriba (craneal) y z hacia delante (anterior), con el
torso centrado y 2 de ancho.
"""
import json
import sys
from pathlib import Path

import fast_simplification
import numpy as np
import SimpleITK as sitk
import trimesh
from PIL import Image
from scipy import ndimage, sparse
from scipy.sparse import csgraph
from skimage import measure

AQUI = Path(__file__).resolve().parent.parent
ISO = 1.5            # mm: las máscaras se pasan a vóxeles cúbicos de este lado antes de hacer la malla
VENTANA = (-150, 900)  # nivel y anchura de la ventana de los cortes (se ve el pulmón y el mediastino)

# Clases de TotalSegmentator («total»), agrupadas en estructuras: (clave, nombre, color, capa, etiquetas, caras)
ESTRUCTURAS = [
    ("pulmon_der", "Pulmón derecho", "#f2b3ae", 1, [12, 13, 14], 6000),
    ("pulmon_izq", "Pulmón izquierdo", "#f2b3ae", 1, [10, 11], 6000),
    ("costillas", "Costillas", "#f1e8d6", 1, list(range(92, 116)) + [117], 14000),
    ("esternon", "Esternón", "#f1e8d6", 1, [116], 1500),
    ("columna", "Columna", "#e9dcc0", 1, list(range(25, 51)), 9000),
    ("cintura", "Clavículas y escápulas", "#efe3cc", 1, [71, 72, 73, 74], 5000),
    ("higado", "Hígado", "#9c3f2e", 1, [5], 5000),
    ("estomago", "Estómago", "#e2a27e", 1, [6], 2500),
    ("bazo", "Bazo", "#7d3550", 1, [1], 1500),
    ("rinones", "Riñones", "#b4513f", 1, [2, 3], 2500),
    ("corazon", "Corazón", "#c8393b", 2, [51, 61], 6000),
    ("aorta", "Aorta", "#e2483f", 2, [52], 3000),
    ("troncos", "Troncos supraaórticos", "#e2483f", 2, [54, 55, 56, 57, 58], 2500),
    ("venas_pulmonares", "Venas pulmonares", "#4c6fd3", 2, [53], 2500),
    ("cavas", "Venas cavas y braquiocefálicas", "#4c6fd3", 2, [59, 60, 62, 63], 3000),
    ("traquea", "Tráquea", "#9fd2e6", 2, [16], 2000),
    ("esofago", "Esófago", "#d79a78", 2, [15], 1500),
]
# Los vasos de la realidad mixta
VASOS = [52, 54, 55, 56, 57, 58, 53, 59, 60, 62, 63]

ct_ruta, seg_ruta = Path(sys.argv[1]), Path(sys.argv[2])
ct = sitk.ReadImage(str(ct_ruta))
a = sitk.GetArrayFromImage(ct).astype(np.float32)                  # z, y, x (LPS: x izquierda, y posterior, z craneal)
seg = sitk.GetArrayFromImage(sitk.ReadImage(str(seg_ruta))).astype(np.int16)
assert seg.shape == a.shape
sx, sy, sz = ct.GetSpacing()
origen = np.asarray(ct.GetOrigin())
assert np.allclose(np.asarray(ct.GetDirection()), np.eye(3).ravel()), "se espera la orientación de CTChest"

# ---- el cuerpo: lo que pasa de -350 UH, sin la camilla (la pieza conexa mayor), con los huecos (pulmones) rellenos
cuerpo = a > -350
cuerpo = ndimage.binary_opening(cuerpo, iterations=2)
etiq, n = ndimage.label(cuerpo)
cuerpo = etiq == (np.argmax(np.bincount(etiq.ravel())[1:]) + 1)
cuerpo = np.stack([ndimage.binary_fill_holes(c) for c in cuerpo])
print("cuerpo:", int(cuerpo.sum()), "vóxeles")


def malla(mascara, caras, suave=1.0):
    """La superficie de una máscara (z, y, x), en mm del espacio del TAC (LPS)."""
    z, y, x = np.nonzero(mascara)
    m = 3
    z0, z1 = max(z.min() - m, 0), min(z.max() + m + 1, mascara.shape[0])
    y0, y1 = max(y.min() - m, 0), min(y.max() + m + 1, mascara.shape[1])
    x0, x1 = max(x.min() - m, 0), min(x.max() + m + 1, mascara.shape[2])
    recorte = mascara[z0:z1, y0:y1, x0:x1].astype(np.float32)
    zoom = (sz / ISO, sy / ISO, sx / ISO)
    v = ndimage.zoom(recorte, zoom, order=1)
    v = np.pad(v, 2)
    v = ndimage.gaussian_filter(v, suave)
    verts, faces, _, _ = measure.marching_cubes(v, 0.5)
    verts = (verts - 2) / np.asarray(zoom) + [z0, y0, x0]           # (índices del TAC: z, y, x)
    mm = np.stack([verts[:, 2] * sx, verts[:, 1] * sy, verts[:, 0] * sz], 1) + origen
    t = trimesh.Trimesh(mm, faces[:, ::-1], process=True)
    trimesh.smoothing.filter_taubin(t, iterations=10)
    if len(t.faces) > caras:
        vv, ff = fast_simplification.simplify(t.vertices, t.faces, target_reduction=1 - caras / len(t.faces))
        t = trimesh.Trimesh(vv, ff, process=True)
    if t.volume < 0:                                                # (las caras, hacia fuera)
        t.invert()
    return t


entero = malla(cuerpo, 40000, suave=1.2)
menor, mayor = entero.bounds
centro = (menor + mayor) / 2
escala = 2.0 / float(mayor[0] - menor[0])                            # 2 de ancho
print("torso:", np.round(mayor - menor), "mm; escala", round(escala, 5))


def a_escena(p):
    v = (np.asarray(p) - centro) * escala
    return np.stack([v[:, 0], v[:, 2], -v[:, 1]], 1)                # (izquierda, craneal, anterior)


# ---- el paquete del torso
salida, trozos, desde = [], [], 0


def guarda(datos, t):
    global desde
    pos = a_escena(t.vertices)
    assert len(pos) < 65536, f"{datos['clave']}: no cabe en índices de 16 bits"
    lo, tam = pos.min(0), np.maximum(np.ptp(pos, axis=0), 1e-9)
    q = np.round((pos - lo) / tam * 65535).astype(np.uint16)
    idx = np.asarray(t.faces, np.uint16).ravel()
    salida.append({**datos, "pos": [desde, len(q)], "idx": [desde + q.nbytes, len(idx)],
                   "min": [round(float(x), 5) for x in lo], "tam": [round(float(x), 5) for x in tam]})
    trozos.extend([q.tobytes(), idx.tobytes()])
    desde += q.nbytes + idx.nbytes


guarda({"clave": "torso", "grupo": "entero"}, entero)
guarda({"clave": "piel", "grupo": "piel", "nombre": "Piel", "color": "#e3b39b", "capa": 0}, malla(cuerpo, 12000, suave=1.2))
mapa_color = np.zeros(seg.shape, np.uint8)
for n, (clave, nombre, color, capa, etiquetas, caras) in enumerate(ESTRUCTURAS, start=1):
    m = np.isin(seg, etiquetas) & cuerpo
    if m.sum() < 200:
        print("  (sin", nombre + ")")
        continue
    mapa_color[m] = n
    t = malla(m, caras, suave=0.8)
    guarda({"clave": clave, "grupo": "organo", "nombre": nombre, "color": color, "capa": capa}, t)
    print(f"  {nombre}: {len(t.faces)} caras")

# ---- los cortes: 14, de abajo arriba, en un cuadrado alrededor del cuerpo
zs_cuerpo = np.nonzero(cuerpo.any(axis=(1, 2)))[0]
ys, xs = np.nonzero(cuerpo.any(axis=0))
cy, cx = (ys.min() + ys.max()) / 2, (xs.min() + xs.max()) / 2
lado = int(round(max(ys.max() - ys.min(), xs.max() - xs.min()) * 1.06))
y0, x0 = int(round(cy - lado / 2)), int(round(cx - lado / 2))


def cuadrado(img, relleno):
    out = np.full((lado, lado) + img.shape[2:], relleno, img.dtype)
    ya, yb, xa, xb = max(0, y0), min(img.shape[0], y0 + lado), max(0, x0), min(img.shape[1], x0 + lado)
    out[ya - y0:yb - y0, xa - x0:xb - x0] = img[ya:yb, xa:xb]
    return out


dentro = ndimage.binary_dilation(cuerpo, iterations=2)              # (sin la camilla: fuera del cuerpo, nada)


def gris(z):
    nivel, ancho = VENTANA
    g = np.clip((a[z] - (nivel - ancho / 2)) / ancho, 0, 1) * dentro[z]
    return (g * 255 + 0.5).astype(np.uint8)


(AQUI / "img").mkdir(exist_ok=True)
zs = np.linspace(zs_cuerpo[0] + 3, zs_cuerpo[-1] - 3, 14).round().astype(int)
for k, z in enumerate(zs):
    c = np.stack([cuadrado(gris(z), 0)] * 3 + [cuadrado((dentro[z] * 235).astype(np.uint8), 0)], -1)
    # (en la escena, la derecha del corte va hacia delante y su parte de arriba, a la derecha del paciente; fuera del
    # cuerpo, transparente)
    c = c.transpose(1, 0, 2)[:, ::-1]
    Image.fromarray(np.ascontiguousarray(c), "RGBA").resize((256, 256), Image.LANCZOS).save(
        AQUI / "img" / f"corte_{k:02d}.webp", quality=82, method=6)
lado_mm, alto_mm = lado * sx, float(zs[-1] - zs[0]) * sz

# ---- la red neuronal: un corte a la altura del corazón, en la orientación de siempre (delante arriba, la derecha del
# paciente a la izquierda de la imagen), y su segmentación con el color de cada estructura
z = int(np.argmax((seg == 51).sum(axis=(1, 2))))
Image.fromarray(cuadrado(gris(z), 0)).resize((384, 384), Image.LANCZOS).save(AQUI / "img" / "red_entrada.webp", quality=86, method=6)
etq = cuadrado(mapa_color[z], 0)
color = np.zeros((lado, lado, 4), np.uint8)
for n, (_, _, hexa, _, _, _) in enumerate(ESTRUCTURAS, start=1):
    color[etq == n] = [int(hexa[i:i + 2], 16) for i in (1, 3, 5)] + [255]
Image.fromarray(color, "RGBA").resize((384, 384), Image.NEAREST).save(AQUI / "img" / "red_salida.png", optimize=True)
print("corte de la red: z =", z)

(AQUI / "modelos").mkdir(exist_ok=True)
(AQUI / "modelos" / "torso.bin").write_bytes(b"".join(trozos))
(AQUI / "modelos" / "torso.json").write_text(json.dumps(
    {"origen": "TAC de tórax «CTChest» (muestras de 3D Slicer), segmentado con TotalSegmentator",
     "lado_cortes": round(lado_mm * escala, 4), "alto_cortes": round(alto_mm * escala, 4),
     "centro_mm": [round(float(x), 4) for x in centro], "escala": escala, "mallas": salida},
    separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
print(len(salida), "mallas,", desde // 1024, "KB")

# ---- los vasos: su superficie, y la distancia de cada vértice al corazón medida por la malla (Dijkstra por las aristas,
# desde los vértices de cada vaso más cercanos al centro del corazón)
vasos = malla(np.isin(seg, VASOS) & cuerpo, 30000, suave=0.7)
vasos = trimesh.Trimesh(vasos.vertices, vasos.faces, process=True)
z_, y_, x_ = np.nonzero(seg == 51)
corazon = np.array([x_.mean() * sx, y_.mean() * sy, z_.mean() * sz]) + origen
aristas = vasos.edges_unique
largo_arista = np.linalg.norm(vasos.vertices[aristas[:, 0]] - vasos.vertices[aristas[:, 1]], axis=1)
nv = len(vasos.vertices)
g = sparse.coo_matrix((largo_arista, (aristas[:, 0], aristas[:, 1])), shape=(nv, nv)).tocsr()
ncomp, comp = csgraph.connected_components(g, directed=False)
dist_corazon = np.linalg.norm(vasos.vertices - corazon, axis=1)
raices = [int(np.flatnonzero(comp == c)[np.argmin(dist_corazon[comp == c])]) for c in range(ncomp)]
largo = csgraph.dijkstra(g, directed=False, indices=raices, min_only=True)
largo[~np.isfinite(largo)] = 0
maximo = float(largo.max())
pos = a_escena(vasos.vertices)
lo, tam = pos.min(0), np.maximum(np.ptp(pos, axis=0), 1e-9)
q = np.round((pos - lo) / tam * 65535).astype(np.uint16)
ql = np.round(largo / maximo * 65535).astype(np.uint16)
idx = np.asarray(vasos.faces, np.uint32).ravel()
(AQUI / "modelos" / "vasos.bin").write_bytes(q.tobytes() + ql.tobytes() + idx.tobytes())
(AQUI / "modelos" / "vasos.json").write_text(json.dumps({
    "origen": "vasos grandes del tórax del mismo TAC (TotalSegmentator)", "vertices": int(len(q)), "indices": int(len(idx)),
    "largo_max_mm": round(maximo, 2), "min": [round(float(x), 5) for x in lo], "tam": [round(float(x), 5) for x in tam],
    "pos": [0, len(q)], "largo": [q.nbytes, len(ql)], "idx": [q.nbytes + ql.nbytes, len(idx)]}), encoding="utf-8")
print("vasos:", len(q), "vértices,", len(idx) // 3, "caras,", ncomp, "piezas, el más largo", round(maximo), "mm")
