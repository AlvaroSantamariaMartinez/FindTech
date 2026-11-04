"""Genera los entregables de comunicación en ``comunicacion/salida/``.

    python3.13 comunicacion/generar.py renders       # imágenes 3D del dosier (dosier/img) desde la presentación
    python3.13 comunicacion/generar.py dosier        # salida/MRAnalyzer-dosier-<versión>.pdf
    python3.13 comunicacion/generar.py presentacion  # salida/MRAnalyzer-presentacion-<versión>.zip (funciona sin internet)
    python3.13 comunicacion/generar.py capturas      # salida/capturas/dNN.png: cada diapositiva, para revisarlas
    python3.13 comunicacion/generar.py todo          # renders + dosier + presentación

Antes, ``actualizar.py`` pone al día las cifras. Necesita node con Playwright (Chromium) y zip de Python.
"""
from __future__ import annotations

import functools
import http.server
import json
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "salida"
NAVEGADOR = AQUI / "recursos" / "navegador.cjs"
# imagen del dosier -> diapositiva de la presentación (índice desde 0)
RENDERS = {"portada": 0, "problema": 1, "solucion": 3, "vasos": 4, "impresion": 5, "xr": 6}
LEEME = """MRAnalyzer — presentación holográfica (reveal.js + Three.js)

CÓMO ABRIRLA (necesita un pequeño servidor local porque carga los modelos 3D):
  1. Abre una terminal en esta carpeta.
  2. Ejecuta:  python -m http.server 8000
  3. En Chrome o Edge abre:  http://localhost:8000/presentacion.html
  4. Pulsa F para pantalla completa y S para la vista del orador (guion y tiempos).

Funciona sin internet (reveal.js y three.js van incluidos); con internet carga además las fuentes.
Usa un portátil con tarjeta gráfica y el navegador actualizado.
Los modelos 3D son reales: generados por MRAnalyzer con muestras públicas de 3D Slicer, no de pacientes.
"""


def version() -> str:
    return json.loads((AQUI / "datos.json").read_text(encoding="utf-8"))["automaticas"]["version"]


class _Servidor:
    """Servidor HTTP local de ``comunicacion/`` (los modelos 3D no cargan desde file://)."""

    def __enter__(self):
        class Silencioso(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

        manejador = functools.partial(Silencioso, directory=str(AQUI))
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manejador)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.srv.server_address[1]}"

    def __exit__(self, *exc):
        self.srv.shutdown()


def navegador(*args):
    subprocess.run(["node", str(NAVEGADOR), *map(str, args)], check=True, cwd=AQUI / "recursos")


def renders():
    with _Servidor() as base:
        navegador("renders", f"{base}/presentacion/presentacion.html", AQUI / "dosier" / "img",
                  *[f"{k}={v}" for k, v in RENDERS.items()])


def capturas():
    (SALIDA / "capturas").mkdir(parents=True, exist_ok=True)
    with _Servidor() as base:
        navegador("capturas", f"{base}/presentacion/presentacion.html", SALIDA / "capturas")
    print(f"Revisa cada una: {SALIDA / 'capturas'}")


def dosier():
    SALIDA.mkdir(exist_ok=True)
    pdf = SALIDA / f"MRAnalyzer-dosier-{version()}.pdf"
    with _Servidor() as base:
        navegador("pdf", f"{base}/dosier/dosier.html", pdf)
    print(pdf)


def presentacion():
    SALIDA.mkdir(exist_ok=True)
    zip_ = SALIDA / f"MRAnalyzer-presentacion-{version()}.zip"
    with zipfile.ZipFile(zip_, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((AQUI / "presentacion").rglob("*")):
            if f.is_file():
                z.write(f, Path("presentacion") / f.relative_to(AQUI / "presentacion"))
        z.writestr("presentacion/LEEME.txt", LEEME)
    print(zip_)


def main():
    if not shutil.which("node"):
        raise SystemExit("Hace falta node (con Playwright) para los renders y el PDF")
    que = sys.argv[1] if len(sys.argv) > 1 else "todo"
    pasos = {"renders": [renders], "dosier": [dosier], "presentacion": [presentacion], "capturas": [capturas],
             "todo": [renders, dosier, presentacion]}
    if que not in pasos:
        raise SystemExit(__doc__)
    for paso in pasos[que]:
        print(f"== {paso.__name__}")
        paso()


if __name__ == "__main__":
    main()
