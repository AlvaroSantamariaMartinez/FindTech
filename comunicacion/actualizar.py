"""Pone al día las cifras de la presentación y del dosier.

1. Recalcula las cifras automáticas desde el repositorio (versión, líneas de código, pruebas que pasan).
2. Las escribe en ``datos.json`` junto a las manuales.
3. Las inyecta en cada elemento con ``data-dato="clave"`` de la presentación y del dosier (texto y, en los
   contadores animados, ``data-hasta``), y la versión en ``<html data-version>``.

Uso (desde FindTech):
    python3.13 comunicacion/actualizar.py            # todo, pasando las pruebas (~2 min)
    python3.13 comunicacion/actualizar.py --rapido   # sin pasar las pruebas (deja su cifra como estaba)
    python3.13 comunicacion/actualizar.py --comprobar # solo dice qué cambiaría
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent / "mranalyzer"  # (FindTech/mranalyzer: el repositorio del programa)
DATOS = AQUI / "datos.json"
DESTINOS = [AQUI / "presentacion" / "presentacion.html", AQUI / "dosier" / "dosier.html"]


def lineas(patron: str) -> int:
    total = 0
    for f in (RAIZ / "mranalyzer").rglob(patron):
        if "vendor" in f.parts or f.name.endswith(".min.js"):
            continue
        try:
            total += sum(1 for _ in f.open(encoding="utf-8", errors="ignore"))
        except OSError:
            pass
    return total


def pruebas() -> tuple[int, int]:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=RAIZ,
                       capture_output=True, text=True, timeout=3600)
    ultima = (r.stdout.strip().splitlines() or [""])[-1]
    ok = int(m.group(1)) if (m := re.search(r"(\d+) passed", ultima)) else 0
    saltadas = int(m.group(1)) if (m := re.search(r"(\d+) skipped", ultima)) else 0
    fallos = int(m.group(1)) if (m := re.search(r"(\d+) failed", ultima)) else 0
    if fallos:
        raise SystemExit(f"Hay {fallos} pruebas que fallan: arréglalas antes de presumir de ellas ({ultima})")
    return ok, ok + saltadas


def automaticas(rapido: bool, antes: dict) -> dict:
    texto = (RAIZ / "mranalyzer" / "__init__.py").read_text(encoding="utf-8")
    version = re.search(r'__version__ = "([^"]+)"', texto).group(1)
    a = {"version": version, "fecha": datetime.date.today().isoformat(),
         "lineas_python": lineas("*.py"), "lineas_js": lineas("*.js")}
    if rapido:
        a["pruebas_ok"], a["pruebas_total"] = antes.get("pruebas_ok"), antes.get("pruebas_total")
    else:
        a["pruebas_ok"], a["pruebas_total"] = pruebas()
    return a


def texto_de(clave: str, valor) -> str:
    if clave.startswith("lineas_"):
        return "≈ " + f"{round(valor, -3):,}".replace(",", "\u00a0")  # (espacio duro: no parte la cifra)
    if isinstance(valor, float):
        return f"{valor:g}".replace(".", ",")
    return str(valor)


ETIQUETA = re.compile(r'(<(\w+)\b[^>]*\bdata-dato="([a-z_]+)"[^>]*>)(.*?)(</\2>)', re.S)


def inyectar(html: str, valores: dict) -> tuple[str, list[str]]:
    sin_valor = []

    def poner(m):
        abre, _, clave, _, cierra = m.groups()
        if clave not in valores:
            sin_valor.append(clave)
            return m.group(0)
        v = valores[clave]
        if "data-hasta=" in abre:  # (contador animado: el número va en data-hasta y el texto empieza en 0)
            abre = re.sub(r'data-hasta="[^"]*"', f'data-hasta="{v}"', abre)
            return abre + "0" + cierra
        return abre + texto_de(clave, v) + cierra

    html = ETIQUETA.sub(poner, html)
    html = re.sub(r'data-version="[^"]*"', f'data-version="{valores["version"]}"', html)
    return html, sin_valor


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rapido", action="store_true", help="sin pasar las pruebas")
    ap.add_argument("--comprobar", action="store_true", help="no escribe nada")
    args = ap.parse_args()
    datos = json.loads(DATOS.read_text(encoding="utf-8"))
    nuevas = automaticas(args.rapido, datos["automaticas"])
    for k, v in nuevas.items():
        if datos["automaticas"].get(k) != v:
            print(f"  {k}: {datos['automaticas'].get(k)} -> {v}")
    datos["automaticas"] = nuevas
    valores = {**nuevas, **{k: d["valor"] for k, d in datos["manuales"].items()}}
    for destino in DESTINOS:
        if not destino.exists():
            continue
        antes = destino.read_text(encoding="utf-8")
        despues, sin_valor = inyectar(antes, valores)
        if sin_valor:
            print(f"  ¡{destino.name}: sin valor para {sorted(set(sin_valor))} (añádelo a datos.json)!")
        print(f"{destino.relative_to(AQUI.parent)}: {'cambia' if despues != antes else 'sin cambios'}")
        if not args.comprobar and despues != antes:
            destino.write_text(despues, encoding="utf-8")
    if not args.comprobar:
        DATOS.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
