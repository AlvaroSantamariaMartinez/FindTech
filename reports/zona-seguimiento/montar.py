"""Monta la página: mete en la plantilla el render de la maqueta y los resultados de la simulación."""
import base64, json, pathlib
aqui = pathlib.Path(__file__).parent
html = (aqui / "plantilla.html").read_text(encoding="utf-8")
html = html.replace("__IMG__", base64.b64encode((aqui / "maqueta.jpg").read_bytes()).decode())
html = html.replace("__DATOS__", json.dumps(json.loads((aqui / "resultados.json").read_text(encoding="utf-8")), ensure_ascii=False))
(aqui / "zona-seguimiento.html").write_text(html, encoding="utf-8")
print(len(html))
