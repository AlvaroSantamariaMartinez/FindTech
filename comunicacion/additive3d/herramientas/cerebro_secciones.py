"""Las secciones del cerebro de la simulación (corteza, sustancia blanca, cerebelo, núcleos, ventrículos…), con MRAnalyzer
sobre la resonancia pública «MRHead» de 3D Slicer. No es un paciente.

    MRANALYZER_ORGANOS_PYTHON=/ruta/al/python/con/pytorch python3 cerebro_secciones.py CARPETA_DEL_ANALISIS DESTINO

CARPETA_DEL_ANALISIS es la salida de MRAnalyzer para MRHead (imagen.nrrd, informe.json y cerebro_completo.stl). Deja en
DESTINO las mallas de las secciones (secciones/*.stl, en el marco de cerebro_completo.stl), su lista (secciones.json), los
cortes de la resonancia (cortes/corte_NN.png), de abajo arriba, y un corte con su segmentación para la diapositiva de la
red neuronal (red_entrada.png y red_salida.png).
"""
import json
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "mranalyzer"))
from mranalyzer import secciones, synthseg  # noqa: E402

analisis, destino = Path(sys.argv[1]), Path(sys.argv[2])
destino.mkdir(parents=True, exist_ok=True)
imagen = sitk.ReadImage(str(analisis / "imagen.nrrd"))
informe = json.loads((analisis / "informe.json").read_text(encoding="utf-8"))

etiquetas = synthseg.en_rejilla(synthseg.segmentar(imagen), imagen)
lista = secciones.generar(etiquetas, imagen, informe["marco_impresion"], destino)
(destino / "secciones.json").write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(lista), "secciones")

# Los cortes: 14, repartidos por donde hay cerebro y recortados a un cuadrado alrededor de él (con algo de cabeza).
a = sitk.GetArrayFromImage(imagen).astype(np.float32)
hay = etiquetas > 0
con_cerebro = np.nonzero(hay.any(axis=(1, 2)))[0]
ys, xs = np.nonzero(hay.any(axis=0))
cy, cx = (ys.min() + ys.max()) / 2, (xs.min() + xs.max()) / 2
lado = int(round(max(ys.max() - ys.min(), xs.max() - xs.min()) * 1.16))
y0, x0 = int(round(cy - lado / 2)), int(round(cx - lado / 2))
lienzo = np.zeros((a.shape[0], lado, lado), np.float32)
ya, yb, xa, xb = max(0, y0), min(a.shape[1], y0 + lado), max(0, x0), min(a.shape[2], x0 + lado)
lienzo[:, ya - y0:yb - y0, xa - x0:xb - x0] = a[:, ya:yb, xa:xb]
alto = np.percentile(a[a > 0], 99.5)
(destino / "cortes").mkdir(exist_ok=True)
zs = np.linspace(con_cerebro[0] + 4, con_cerebro[-1] - 4, 14).round().astype(int)
for k, z in enumerate(zs):
    corte = np.clip(lienzo[z] / alto, 0, 1) ** 0.8
    Image.fromarray((corte * 255 + 0.5).astype(np.uint8)).save(destino / "cortes" / f"corte_{k:02d}.png")
v = float(imagen.GetSpacing()[0])
(destino / "cortes.json").write_text(json.dumps({"lado_mm": lado * v, "alto_mm": float(zs[-1] - zs[0]) * v}), encoding="utf-8")
print("cortes de z =", zs[0], "a", zs[-1], "lado", lado * v, "mm")

# Para la diapositiva de la red neuronal: un corte (con la frente arriba) y su segmentación, cada sección con su color.
z = int(zs[8])
Image.fromarray((np.clip(lienzo[z] / alto, 0, 1) ** 0.8 * 255 + 0.5).astype(np.uint8)[::-1]).save(destino / "red_entrada.png")
de_seccion = np.zeros((lado, lado), np.uint8)
de_seccion[ya - y0:yb - y0, xa - x0:xb - x0] = secciones.mapa(etiquetas)[z, ya:yb, xa:xb]
color = np.zeros((lado, lado, 4), np.uint8)
for n, (_, _, _, _, hexa, _) in enumerate(secciones.SECCIONES, start=1):
    color[de_seccion == n] = [int(hexa[i:i + 2], 16) for i in (1, 3, 5)] + [255]
Image.fromarray(color[::-1], "RGBA").save(destino / "red_salida.png")
