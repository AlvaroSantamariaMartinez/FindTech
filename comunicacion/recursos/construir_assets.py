"""Recursos de la presentación: mallas reales de MRAnalyzer (muestras públicas de 3D Slicer) en un binario compacto y
cortes del TAC en PNG.

Uso: python3.13 construir_assets.py <carpeta_con_resultados> <destino_assets>
<carpeta_con_resultados> debe tener: opt_tac/salida (TAC CTChest analizado con MRAnalyzer), opt/cerebro_antes
(RM MRHead analizada), vasos/slicer_lung_vessels.nii.gz (lung_vessels de TotalSegmentator) y
datos_prueba/ct_slicer.nrrd. Son muestras públicas de 3D Slicer: nunca datos de pacientes."""
import json
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import trimesh
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mranalyzer"))
from mranalyzer import malla, organos  # noqa: E402

S, D = Path(sys.argv[1]), Path(sys.argv[2])
D.mkdir(parents=True, exist_ok=True)


def empaquetar(nombre: str, piezas: list[tuple[str, str, trimesh.Trimesh]], centro, escala):
    """Binario: por pieza, posiciones float32 (x, y, z centradas y escaladas, y arriba) + índices uint32."""
    manifiesto, trozos, desplaz = [], [], 0
    for clave, grupo, m in piezas:
        v = (np.asarray(m.vertices, np.float64) - centro) * escala
        v = np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1).astype(np.float32)  # (z del paciente hacia arriba)
        f = np.asarray(m.faces, np.uint32).ravel()
        manifiesto.append({"clave": clave, "grupo": grupo, "pos": [desplaz, len(v)], "idx": [desplaz + v.nbytes, len(f)]})
        trozos += [v.tobytes(), f.tobytes()]
        desplaz += v.nbytes + f.nbytes
    (D / f"{nombre}.bin").write_bytes(b"".join(trozos))
    (D / f"{nombre}.json").write_text(json.dumps(manifiesto), encoding="utf-8")
    print(nombre, len(piezas), "piezas", round(desplaz / 1e6, 2), "MB", sum(p["idx"][1] // 3 for p in manifiesto), "caras")


def cargar(ruta, caras):
    m = trimesh.load(ruta, force="mesh")
    if len(m.faces) > caras:
        m = m.simplify_quadric_decimation(face_count=caras)
    return m


# --- tórax (CTChest de 3D Slicer, 87 estructuras de MRAnalyzer)
est = S / "opt_tac/salida/estructuras"
piezas = []
for f in sorted(est.glob("*.stl")):
    clave = f.stem
    grupo = organos.CATALOGO[clave].grupo if clave in organos.CATALOGO else "otro"
    if clave in ("esqueleto", "otros_huesos") or clave.startswith("hueso_"):
        continue
    objetivo = 5000 if grupo in ("organo", "vaso") else 2200
    if clave.startswith("lung_") and "lobe" in clave:
        objetivo = 5000
    if clave in ("lung_arteries", "lung_veins", "lung_airways"):
        objetivo = 16000
    piezas.append((clave, grupo, cargar(f, objetivo)))
# Vasos pulmonares (modelo lung_vessels de TotalSegmentator sobre el mismo TAC), en el marco de las otras mallas:
# rejilla del análisis (imagen.nrrd, vóxel v) desplazada como al exportar (marco_impresion del informe).
from mranalyzer import cuerpo  # noqa: E402

inf = json.loads((S / "opt_tac/salida/informe.json").read_text(encoding="utf-8"))
marco = np.array(inf["marco_impresion"])
rejilla = sitk.ReadImage(str(S / "opt_tac/salida/imagen.nrrd"))
v = rejilla.GetSpacing()[0]
vas = sitk.Resample(sitk.ReadImage(str(S / "vasos/slicer_lung_vessels.nii.gz")), rejilla, sitk.Transform(),
                    sitk.sitkNearestNeighbor, 0)
va = sitk.GetArrayFromImage(vas)
for k, clave in ((3, "lung_arteries"), (4, "lung_veins"), (1, "lung_airways")):
    m = cuerpo._malla(va == k, v, 6, 16000, sigma=(0.8, 0.8, 0.8))
    if m is not None:
        m.apply_transform(marco)
        m = m.simplify_quadric_decimation(face_count=40000 if k == 3 else 25000)
        piezas.append((clave, "vaso" if k != 1 else "via_aerea", m))
        print(clave, len(m.faces))
todo = trimesh.util.concatenate([p[2] for p in piezas])
lo, hi = todo.bounds
centro = (lo + hi) / 2
escala = 2.0 / float((hi - lo).max())
empaquetar("torax", piezas, centro, escala)

# --- cerebro (MRHead de 3D Slicer) y sus 3 piezas de impresión
cb = S / "opt/cerebro_antes"
cer = cargar(cb / "cerebro_completo.stl", 60000)
lo, hi = cer.bounds
c2, e2 = (lo + hi) / 2, 2.0 / float((hi - lo).max())
empaquetar("cerebro", [("cerebro", "cerebro", cer)], c2, e2)
pz = [(f"pieza_{i}", "pieza", cargar(cb / f"pieza_{i}.stl", 25000)) for i in (1, 2, 3)]
t = trimesh.util.concatenate([p[2] for p in pz])
lo, hi = t.bounds
empaquetar("piezas", pz, (lo + hi) / 2, 2.0 / float((hi - lo).max()))

# --- cortes axiales del TAC (ventana amplia), para la pila de imágenes
img = sitk.ReadImage(str(S / "datos_prueba/ct_slicer.nrrd"))
a = sitk.GetArrayFromImage(img).astype(np.float32)
n = a.shape[0]
for k, z in enumerate(np.linspace(n * 0.12, n * 0.9, 14).astype(int)):
    c = np.clip((a[z] + 1000) / 1400, 0, 1)
    rgba = np.zeros(c.shape + (4,), np.uint8)
    rgba[..., 0] = (c * 140).astype(np.uint8)
    rgba[..., 1] = (c * 235).astype(np.uint8)
    rgba[..., 2] = (c * 255).astype(np.uint8)
    rgba[..., 3] = (np.clip(c * 1.6, 0, 1) * 255).astype(np.uint8)
    im = Image.fromarray(rgba[::-1] if False else rgba).resize((384, 384), Image.LANCZOS)
    im.save(D / f"corte_{k:02d}.png", optimize=True)
print("cortes", 14)
