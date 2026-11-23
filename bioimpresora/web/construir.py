"""Empaqueta la aplicación web en un único HTML descargable y autónomo.

    python construir.py [--three ruta/three.min.js]

Genera ../BioImpresora.html incrustando Three.js (MIT), core.js, worker.js,
app.js y estilo.css. El resultado funciona sin conexión con doble clic.
"""

import argparse
import pathlib
import urllib.request

AQUI = pathlib.Path(__file__).parent
URL_THREE = "https://cdn.jsdelivr.net/npm/three@0.158.0/build/three.min.js"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--three", help="ruta local a three.min.js r158 (si no, se descarga)")
    ap.add_argument("--salida", default=str(AQUI.parent / "BioImpresora.html"))
    a = ap.parse_args()
    if a.three:
        three = pathlib.Path(a.three).read_text(encoding="utf-8")
    else:
        three = urllib.request.urlopen(URL_THREE).read().decode("utf-8")
    three = three.replace("</script", "<\\/script")
    html = (AQUI / "plantilla.html").read_text(encoding="utf-8")
    for marca, contenido in (
        ("/*__CSS__*/", (AQUI / "estilo.css").read_text(encoding="utf-8")),
        ("/*__THREE__*/", three),
        ("/*__CORE__*/", (AQUI / "core.js").read_text(encoding="utf-8")),
        ("/*__WORKER__*/", (AQUI / "worker.js").read_text(encoding="utf-8")),
        ("/*__APP__*/", (AQUI / "app.js").read_text(encoding="utf-8")),
    ):
        assert marca in html, marca
        html = html.replace(marca, contenido, 1)
    pathlib.Path(a.salida).write_text(html, encoding="utf-8")
    print(f"OK → {a.salida} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
