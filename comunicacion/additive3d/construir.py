"""Monta la presentación de Additive 3D Engineering en un solo archivo HTML que se abre con doble clic, sin servidor y
sin internet: estilos, tipografía, fotos, modelos 3D, reveal.js y three.js van dentro.

    python3 comunicacion/additive3d/construir.py            # salida/Additive3D-presentacion.html
    python3 comunicacion/additive3d/construir.py capturas   # además, una imagen por diapositiva en salida/capturas-additive3d
    python3 comunicacion/additive3d/construir.py artefacto  # salida/artefacto-additive3d: la copia para publicarla en línea

Para trabajar en ella se abre ``presentacion.html`` con un servidor local (``python -m http.server`` en ``comunicacion/``).
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
VENDOR = AQUI.parent / "presentacion" / "vendor"
SALIDA = AQUI.parent / "salida"
TIPOS = {".webp": "image/webp", ".png": "image/png", ".woff2": "font/woff2", ".bin": "application/octet-stream", ".json": "application/json"}


def uri(f: Path) -> str:
    tipo = TIPOS.get(f.suffix) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    return f"data:{tipo};base64,{base64.b64encode(f.read_bytes()).decode('ascii')}"


def guion(texto: str) -> str:
    """Un guion metido en el HTML no puede llevar su propia etiqueta de cierre."""
    return texto.replace("</script", "<\\/script")


def construir(artefacto: bool = False) -> Path:
    """Con ``artefacto``, la copia para publicar como página en línea: sin la envoltura del documento (la pone quien la
    publica), con three.js en un archivo aparte, junto a la página, y sin llevar la diapositiva en la dirección."""
    html = (AQUI / "presentacion.html").read_text(encoding="utf-8")

    # estilos (con la tipografía dentro)
    css = "\n".join((VENDOR / n).read_text(encoding="utf-8") for n in ("reset.css", "reveal.css"))
    css += "\n" + (AQUI / "estilos.css").read_text(encoding="utf-8")
    css = re.sub(r"url\((fuentes/[^)]+)\)", lambda m: f"url({uri(AQUI / m.group(1))})", css)
    html = re.sub(r'\s*<link rel="stylesheet" href="[^"]+">', "", html)
    html = html.replace("</head>", f"<style>\n{css}\n</style>\n</head>")

    # fotos de las diapositivas
    html = re.sub(r'src="(img/[^"]+)"', lambda m: f'src="{uri(AQUI / m.group(1))}"', html)

    # lo que la escena pide por su nombre: los cortes del TAC y los modelos
    embebidos = {f"img/{f.name}": uri(f) for f in sorted([*(AQUI / "img").glob("corte_*.webp"), *(AQUI / "img").glob("red_*")])}
    embebidos |= {f"modelos/{f.name}": uri(f) for f in sorted((AQUI / "modelos").iterdir())}
    three = base64.b64encode((VENDOR / "three.module.min.js").read_bytes()).decode("ascii")
    if artefacto:
        donde = 'new URL("three.module.min.js", document.baseURI).href'
    else:
        donde = f'URL.createObjectURL(new Blob([Uint8Array.from(atob("{three}"), c => c.charCodeAt(0))], {{ type: "text/javascript" }}))'
    datos = f"""<script>
window.__embebidos = {json.dumps(embebidos)};
window.__three = {donde};
</script>"""

    # los dos módulos, en uno: la escena dentro de su propia función y la aplicación detrás
    escena = (AQUI / "escena.js").read_text(encoding="utf-8")
    escena, n = re.subn(r"^import \* as THREE from [^\n]+\n", "const THREE = await import(window.__three);\n", escena, flags=re.M)
    assert n == 1, "no encuentro la línea que importa three.js en escena.js"
    exporta = re.findall(r"^export (?:async )?(?:function|const|let) (\w+)", escena, flags=re.M)
    escena = re.sub(r"^export ", "", escena, flags=re.M)
    app = (AQUI / "app.js").read_text(encoding="utf-8")
    app, n = re.subn(r"^import \{([^}]+)\} from './escena.js';\n", "", app, flags=re.M)
    assert n == 1, "no encuentro la línea que importa la escena en app.js"
    if artefacto:
        assert app.count("hash: true") == 1
        app = app.replace("hash: true", "hash: false")
    modulo = (f"const __escena = await (async () => {{\n{escena}\nreturn {{ {', '.join(exporta)} }};\n}})();\n"
              f"const {{ {', '.join(exporta)} }} = __escena;\n{{\n{app}\n}}\n")

    guiones = "\n".join(f"<script>\n{guion((VENDOR / n).read_text(encoding='utf-8'))}\n</script>" for n in ("reveal.js", "notes.js"))
    html, n = re.subn(r'\s*<script src="[^"]+"></script>\s*<script src="[^"]+"></script>\s*<script type="module" src="app.js"></script>',
                      lambda m: f"\n{datos}\n{guiones}\n<script type=\"module\">\n{guion(modulo)}</script>", html)
    assert n == 1, "no encuentro los guiones del final de presentacion.html"

    SALIDA.mkdir(exist_ok=True)
    if artefacto:
        carpeta = SALIDA / "artefacto-additive3d"
        carpeta.mkdir(exist_ok=True)
        estilo = re.search(r"<style>.*?</style>", html, flags=re.S).group(0)
        cuerpo = re.search(r"<body[^>]*>(.*)</body>", html, flags=re.S).group(1)
        (carpeta / "three.module.min.js").write_bytes((VENDOR / "three.module.min.js").read_bytes())
        destino = carpeta / "additive3d.html"
        destino.write_text(f"<title>Additive 3D Engineering</title>\n{estilo}\n{cuerpo}", encoding="utf-8")
        print(destino, f"{destino.stat().st_size / 1e6:.1f} MB")
        return destino
    destino = SALIDA / "Additive3D-presentacion.html"
    destino.write_text(html, encoding="utf-8")
    print(destino, f"{destino.stat().st_size / 1e6:.1f} MB")
    return destino


def capturas(archivo: Path):
    carpeta = SALIDA / "capturas-additive3d"
    carpeta.mkdir(parents=True, exist_ok=True)
    subprocess.run(["node", str(AQUI / "herramientas" / "capturas.cjs"), archivo.as_uri(), str(carpeta),
                    "0,1,2,3,4,5,6,6:0,6:1,6:2,6:3,6:4,6:5,7,8,9,10,11,12,12:f"], check=True, cwd=AQUI / "herramientas")
    print(f"Revisa cada una: {carpeta}")


if __name__ == "__main__":
    que = sys.argv[1] if len(sys.argv) > 1 else ""
    hecho = construir(artefacto=que == "artefacto")
    if que == "capturas":
        capturas(hecho)
