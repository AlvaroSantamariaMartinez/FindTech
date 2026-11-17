"""Prepara los recursos de la presentación de Additive 3D Engineering. Se ejecuta una vez (o cuando cambie el PowerPoint
o los modelos de la otra presentación):

    python3 comunicacion/additive3d/herramientas/preparar.py CARPETA_DEL_PPTX_DESCOMPRIMIDO

- Las fotos del PowerPoint pasan a ``img/`` en WebP, al tamaño que se usa en pantalla.
- Los cortes del TAC y los modelos 3D salen de ``../presentacion/assets`` (muestras públicas de 3D Slicer, no pacientes).
  Los modelos se guardan en ``modelos/`` con las posiciones y los índices en 16 bits: pesan menos de la mitad.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

AQUI = Path(__file__).resolve().parent.parent
ORIGEN = AQUI.parent / "presentacion" / "assets"
# imagen del PowerPoint -> (nombre, lado mayor en píxeles)
FOTOS = {5: ("corazon", 1000), 7: ("nariz", 1000), 8: ("impresora", 760), 12: ("gafas", 700),
         13: ("manos", 1400), 16: ("corazon2", 1000), 20: ("pelvis", 900)}


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
    for i in range(14):
        im = Image.open(ORIGEN / f"corte_{i:02d}.png").convert("L")
        im.thumbnail((384, 384), Image.LANCZOS)
        im.save(AQUI / "img" / f"corte_{i:02d}.webp", quality=80, method=6)


def modelo(nombre: str):
    """Del paquete de la otra presentación (posiciones float32 e índices uint32) a uno de 16 bits. Cada malla lleva su
    caja (``min`` y ``tam``): la posición es min + q / 65535 · tam."""
    (AQUI / "modelos").mkdir(exist_ok=True)
    manifiesto = json.loads((ORIGEN / f"{nombre}.json").read_text(encoding="utf-8"))
    datos = (ORIGEN / f"{nombre}.bin").read_bytes()
    salida, trozos, desde = [], [], 0
    for p in manifiesto:
        pos = np.frombuffer(datos, np.float32, p["pos"][1] * 3, p["pos"][0]).reshape(-1, 3)
        idx = np.frombuffer(datos, np.uint32, p["idx"][1], p["idx"][0])
        assert len(pos) < 65536, "esta malla no cabe en índices de 16 bits"
        menor, tam = pos.min(0), np.maximum(np.ptp(pos, axis=0), 1e-9)
        q = np.round((pos - menor) / tam * 65535).astype(np.uint16)
        i16 = idx.astype(np.uint16)
        salida.append({"clave": p["clave"], "grupo": p["grupo"], "pos": [desde, len(q)], "idx": [desde + q.nbytes, len(i16)],
                       "min": [round(float(x), 5) for x in menor], "tam": [round(float(x), 5) for x in tam]})
        trozos += [q.tobytes(), i16.tobytes()]
        desde += q.nbytes + i16.nbytes
    (AQUI / "modelos" / f"{nombre}.bin").write_bytes(b"".join(trozos))
    (AQUI / "modelos" / f"{nombre}.json").write_text(json.dumps(salida, separators=(",", ":")), encoding="utf-8")
    print(nombre, len(salida), "mallas", desde // 1024, "KB (antes", len(datos) // 1024, "KB)")


if __name__ == "__main__":
    fotos(Path(sys.argv[1]))
    for m in ("torax", "cerebro"):
        modelo(m)
