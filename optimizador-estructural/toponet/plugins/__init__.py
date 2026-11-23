"""Sistema de plugins de optimizadores.

Cualquier modelo (clásico, red neuronal, híbrido, un servicio externo...) se
integra en la WebUI implementando `OptimizerPlugin` y decorándolo con `@register`.

Se cargan automáticamente:
  * los módulos de este paquete (`toponet/plugins/*.py`), y
  * cualquier `*.py` de la carpeta `plugins/` en la raíz del proyecto
    (o de la ruta indicada en la variable de entorno TOPONET_PLUGINS),
    para que añadas los tuyos sin tocar el código de la aplicación.

Ejemplo mínimo::

    from toponet.plugins import OptimizerPlugin, Param, register

    @register
    class MiModelo(OptimizerPlugin):
        id = "mi_modelo"
        name = "Mi modelo"
        description = "Qué hace"
        params = [Param("agresividad", "float", 0.5, min=0, max=1, step=0.05)]

        def optimize(self, problem, params, progress):
            ...
            return densidad  # np.ndarray (nx, ny, nz) en [0, 1]

Ver `guia/08-webui-y-plugins.md`.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import sys
import traceback
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

ProgressFn = Callable[[float, str], None]


@dataclass
class Param:
    """Descripción de un parámetro: la WebUI genera el control automáticamente."""

    name: str
    type: str  # "int" | "float" | "bool" | "choice"
    default: Any
    label: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    choices: List[str] = field(default_factory=list)
    help: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label or self.name
        return d

    def coerce(self, value: Any) -> Any:
        if value is None:
            return self.default
        if self.type == "int":
            v = int(round(float(value)))
        elif self.type == "float":
            v = float(value)
        elif self.type == "bool":
            v = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "on", "yes", "sí", "si")
            return v
        else:
            v = str(value)
            if self.choices and v not in self.choices:
                v = self.default
            return v
        if self.min is not None:
            v = max(v, type(v)(self.min))
        if self.max is not None:
            v = min(v, type(v)(self.max))
        return v


class OptimizerPlugin:
    """Clase base de todos los optimizadores."""

    id: str = "base"
    name: str = "Optimizador"
    description: str = ""
    kind: str = "otro"  # "clásico" | "neuronal" | "híbrido" | "heurístico" | ...
    params: List[Param] = []

    def available(self) -> Tuple[bool, str]:
        """¿Puede ejecutarse? (dependencias, checkpoints...). Devuelve (ok, motivo)."""
        return True, ""

    def get_params(self) -> List[Param]:
        """Los parámetros pueden ser dinámicos (p. ej. lista de checkpoints)."""
        return list(self.params)

    def resolve_params(self, values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        values = values or {}
        return {p.name: p.coerce(values.get(p.name, p.default)) for p in self.get_params()}

    def optimize(self, problem, params: Dict[str, Any], progress: ProgressFn) -> np.ndarray:
        raise NotImplementedError

    def info(self) -> dict:
        ok, why = self.available()
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "available": ok,
            "unavailable_reason": why,
            "params": [p.to_dict() for p in self.get_params()],
        }


_REGISTRY: Dict[str, OptimizerPlugin] = {}
_LOAD_ERRORS: List[str] = []
_LOADED = False


def register(cls):
    """Decorador: instancia y registra el plugin."""
    inst = cls()
    _REGISTRY[inst.id] = inst
    return cls


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_plugins(extra_dirs: Optional[List[str]] = None, force: bool = False) -> Dict[str, OptimizerPlugin]:
    global _LOADED
    if _LOADED and not force:
        return _REGISTRY
    if force:
        _REGISTRY.clear()
        _LOAD_ERRORS.clear()
    # 1) plugins incluidos
    for mod in pkgutil.iter_modules(__path__):
        name = f"{__name__}.{mod.name}"
        try:
            if force and name in sys.modules:
                importlib.reload(sys.modules[name])
            else:
                importlib.import_module(name)
        except Exception:
            _LOAD_ERRORS.append(f"{name}: {traceback.format_exc(limit=2)}")
    # 2) plugins del usuario
    dirs = list(extra_dirs or [])
    env = os.environ.get("TOPONET_PLUGINS")
    if env:
        dirs += env.split(os.pathsep)
    dirs.append(os.path.join(_project_root(), "plugins"))
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            path = os.path.join(d, fn)
            modname = f"toponet_user_plugin_{os.path.splitext(fn)[0]}"
            try:
                spec = importlib.util.spec_from_file_location(modname, path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[modname] = module
                spec.loader.exec_module(module)
            except Exception:
                _LOAD_ERRORS.append(f"{path}: {traceback.format_exc(limit=2)}")
    _LOADED = True
    return _REGISTRY


def get_plugin(pid: str) -> OptimizerPlugin:
    load_plugins()
    return _REGISTRY[pid]


def list_plugins() -> List[dict]:
    load_plugins()
    return [p.info() for p in _REGISTRY.values()]


def load_errors() -> List[str]:
    return list(_LOAD_ERRORS)
