"""Rutas de la aplicación, tanto en modo desarrollo como empaquetada (PyInstaller).

* `bundle_dir()`: donde están los recursos incluidos (código, web, ejemplos,
  checkpoint preentrenado). En el ejecutable es la carpeta temporal/interna.
* `user_dir()`: carpeta del usuario. En el ejecutable es la carpeta donde está el
  propio ejecutable: ahí van TUS checkpoints (`checkpoints/`), TUS plugins
  (`plugins/`) y los datos que generes (`data/`).
"""
from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> str:
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def user_dir() -> str:
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return bundle_dir()


def search_dirs(name: str) -> list:
    """Carpetas `name` donde buscar, sin duplicados y por prioridad: la carpeta desde la que
    se ejecuta el programa, la del ejecutable y la de los recursos incluidos. Así un
    checkpoint guardado con `entrenar --out checkpoints/x.pt` aparece siempre en la WebUI."""
    out = []
    for base in (os.getcwd(), user_dir(), bundle_dir()):
        d = os.path.join(base, name)
        if d not in out:
            out.append(d)
    return out
