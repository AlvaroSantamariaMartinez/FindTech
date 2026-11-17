"""Prepara los recursos de la presentación de Additive 3D Engineering. Se ejecuta una vez (o cuando cambien el PowerPoint
o el cerebro):

    python3 comunicacion/additive3d/herramientas/preparar.py fotos PPTX_DESCOMPRIMIDO
    python3 comunicacion/additive3d/herramientas/preparar.py cerebro ANALISIS SECCIONES

- ``fotos``: las fotos del PowerPoint pasan a ``img/`` en WebP, al tamaño que se usa en pantalla.
- ``cerebro``: el cerebro de la portada y de la simulación. ANALISIS es la salida de MRAnalyzer para la resonancia
  pública «MRHead» de 3D Slicer (``cerebro_completo.stl``) y SECCIONES, lo que deja ``cerebro_secciones.py`` (las mallas
  de sus secciones y los cortes de la resonancia). No hay datos de pacientes. Las mallas se guardan en ``modelos/`` con
  las posiciones y los índices en 16 bits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

AQUI = Path(__file__).resolve().parent.parent
# imagen del PowerPoint -> (nombre, lado mayor en píxeles)
FOTOS = {5: ("corazon", 1000), 7: ("nariz", 1000), 8: ("impresora", 1000), 12: ("gafas", 700),
         13: ("manos", 1400), 16: ("corazon2", 1000), 20: ("pelvis", 900)}
# caras de cada malla del cerebro (las que no están aquí, 2500 como mucho)
CARAS = {"cerebro": 60000, "corteza": 30000, "sustancia_blanca": 14000, "cerebelo": 8000, "tronco_encefalico": 6000,
         "ventriculo_lateral": 4000}


def sin_blanco(im: Image.Image) -> Image.Image:
    """Una foto sobre fondo blanco, con el blanco hecho transparencia: puesta sobre blanco se ve igual que la original, y
    sobre un fondo claro no deja el recuadro."""
    c = np.asarray(im.convert("RGB"), np.float32) / 255
    alfa = np.clip((1 - c.min(2)) * 1.6, 0, 1)[..., None]
    color = np.where(alfa > 1e-3, (c - (1 - alfa)) / np.maximum(alfa, 1e-3), 1.0)
    return Image.fromarray((np.concatenate([np.clip(color, 0, 1), alfa], 2) * 255 + 0.5).astype(np.uint8), "RGBA")


def fotos(pptx: Path):
    (AQUI / "img").mkdir(exist_ok=True)
    for n, (nombre, lado) in FOTOS.items():
        im = Image.open(pptx / "ppt" / "media" / f"image{n}.png")
        im.thumbnail((lado, lado), Image.LANCZOS)
        if im.mode != "RGBA":
            im = sin_blanco(im)
        im.save(AQUI / "img" / f"{nombre}.webp", quality=86, method=6)
        print(nombre, im.size, (AQUI / "img" / f"{nombre}.webp").stat().st_size // 1024, "KB")


def cerebro(analisis: Path, secciones: Path):
    """Un paquete con el cerebro entero y sus secciones. Cada malla lleva su caja (``min`` y ``tam``): la posición es
    min + q / 65535 · tam. Quedan centradas, con 2 de largo y el eje vertical del paciente hacia arriba (y)."""
    import trimesh

    def cargar(ruta, caras):
        m = trimesh.load(ruta, force="mesh")
        return m.simplify_quadric_decimation(face_count=caras) if len(m.faces) > caras else m

    entero = cargar(analisis / "cerebro_completo.stl", CARAS["cerebro"])
    menor, mayor = entero.bounds
    centro, escala = (menor + mayor) / 2, 2.0 / float((mayor - menor).max())
    mallas = [({"clave": "cerebro", "grupo": "entero"}, entero)]
    for s in json.loads((secciones / "secciones.json").read_text(encoding="utf-8")):
        base = s["clave"].removesuffix("_izq").removesuffix("_der")
        mallas.append(({"clave": s["clave"], "grupo": s["grupo"], "nombre": s["nombre"], "color": s["color"], "capa": s["capa"]},
                       cargar(secciones / s["archivo"], CARAS.get(base, 2500))))
    salida, trozos, desde = [], [], 0
    for datos, m in mallas:
        v = (np.asarray(m.vertices, np.float64) - centro) * escala
        pos = np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1)
        assert len(pos) < 65536, "esta malla no cabe en índices de 16 bits"
        lo, tam = pos.min(0), np.maximum(np.ptp(pos, axis=0), 1e-9)
        q = np.round((pos - lo) / tam * 65535).astype(np.uint16)
        idx = np.asarray(m.faces, np.uint16).ravel()
        salida.append({**datos, "pos": [desde, len(q)], "idx": [desde + q.nbytes, len(idx)],
                       "min": [round(float(x), 5) for x in lo], "tam": [round(float(x), 5) for x in tam]})
        trozos += [q.tobytes(), idx.tobytes()]
        desde += q.nbytes + idx.nbytes
    cortes = json.loads((secciones / "cortes.json").read_text(encoding="utf-8"))
    (AQUI / "modelos").mkdir(exist_ok=True)
    (AQUI / "modelos" / "cerebro.bin").write_bytes(b"".join(trozos))
    (AQUI / "modelos" / "cerebro.json").write_text(json.dumps(
        {"lado_cortes": round(cortes["lado_mm"] * escala, 4), "alto_cortes": round(cortes["alto_mm"] * escala, 4), "mallas": salida},
        separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(len(salida), "mallas", desde // 1024, "KB")
    for f in sorted((secciones / "cortes").glob("corte_*.png")):
        Image.open(f).convert("L").resize((256, 256), Image.LANCZOS).save(AQUI / "img" / f"{f.stem}.webp", quality=82, method=6)
    # el corte de la diapositiva de la red neuronal y su segmentación (esta, sin suavizar: son etiquetas)
    Image.open(secciones / "red_entrada.png").convert("L").resize((384, 384), Image.LANCZOS).save(AQUI / "img" / "red_entrada.webp", quality=86, method=6)
    Image.open(secciones / "red_salida.png").resize((384, 384), Image.NEAREST).save(AQUI / "img" / "red_salida.png", optimize=True)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "fotos":
        fotos(Path(sys.argv[2]))
    elif len(sys.argv) > 3 and sys.argv[1] == "cerebro":
        cerebro(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit(__doc__)
