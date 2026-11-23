"""Configuración de hardware y parámetros de proceso de la bioimpresora.

La máquina modelada tiene cuatro brazos cartesianos independientes que
comparten la misma plataforma de impresión:

* ``E1``  – extrusor neumático 1 (material A, biopolímero estructural).
* ``E2``  – extrusor neumático 2 (material B, biotinta cargada con células).
* ``UV``  – brazo con guía de luz UV que fotopolimeriza el primer/fotoiniciador.
* ``AUX`` – brazo auxiliar, actualmente sin uso (permanece estacionado).

Unidades: mm, s, kPa, mW/cm², mJ/cm².
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace

# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------


@dataclass
class ConfigBrazo:
    nombre: str
    tipo: str  # "extrusor" | "uv" | "auxiliar"
    posicion_reposo: tuple[float, float]  # (x, y) en mm, fuera de la pieza
    velocidad_viaje_mm_s: float = 40.0
    aceleracion_mm_s2: float = 600.0
    radio_cabezal_mm: float = 1.5  # radio de exclusión de la punta (colisiones)
    activo: bool = True
    rol: str = ""  # descripción libre del uso del brazo


@dataclass
class ConfigExtrusor(ConfigBrazo):
    diametro_boquilla_mm: float = 0.25
    longitud_boquilla_mm: float = 6.0
    material: str = "A"


@dataclass
class ConfigUV(ConfigBrazo):
    longitud_onda_nm: float = 365.0
    diametro_spot_mm: float = 4.0
    intensidad_max_mw_cm2: float = 100.0
    separacion_pasadas_mm: float = 3.2  # distancia entre filas del barrido UV


@dataclass
class Bioimpresora:
    e1: ConfigExtrusor = field(
        default_factory=lambda: ConfigExtrusor(
            nombre="E1", tipo="extrusor", posicion_reposo=(-30.0, 0.0),
            material="A", rol="Extrusor material estructural",
        )
    )
    e2: ConfigExtrusor = field(
        default_factory=lambda: ConfigExtrusor(
            nombre="E2", tipo="extrusor", posicion_reposo=(30.0, 0.0),
            material="B", rol="Extrusor biotinta celular",
        )
    )
    uv: ConfigUV = field(
        default_factory=lambda: ConfigUV(
            nombre="UV", tipo="uv", posicion_reposo=(0.0, 30.0),
            radio_cabezal_mm=2.5, rol="Fotocurado UV del primer",
        )
    )
    aux: ConfigBrazo = field(
        default_factory=lambda: ConfigBrazo(
            nombre="AUX", tipo="auxiliar", posicion_reposo=(0.0, -30.0),
            activo=False, rol="Sin uso (reservado: cámara, 3er material, pinza...)",
        )
    )
    tiempo_cambio_capa_s: float = 0.5

    def brazos(self) -> list[ConfigBrazo]:
        return [self.e1, self.e2, self.uv, self.aux]

    def a_dict(self) -> dict:
        return {b.nombre: asdict(b) for b in self.brazos()}


# ---------------------------------------------------------------------------
# Parámetros de proceso (lo que la IA aprende a ajustar)
# ---------------------------------------------------------------------------

MODOS = ("por_capa+secuencial", "por_capa+paralelo", "seguimiento+secuencial")


@dataclass
class ParametrosProceso:
    presion_e1_kpa: float = 110.0
    presion_e2_kpa: float = 85.0
    velocidad_mm_s: float = 8.0
    altura_capa_mm: float = 0.3
    intensidad_uv_mw_cm2: float = 20.0
    velocidad_uv_mm_s: float = 3.0
    retardo_uv_s: float = 1.0
    fotoiniciador_pct: float = 0.5
    # "por_capa": el brazo UV barre la capa completa al terminar de depositarla.
    # "seguimiento": el brazo UV sigue al extrusor activo con un retardo.
    modo_uv: str = "por_capa"
    # "secuencial": E1 y luego E2. "paralelo": ambos a la vez con antichoque.
    estrategia: str = "secuencial"

    @property
    def modo(self) -> str:
        return f"{self.modo_uv}+{self.estrategia}"

    def validar(self) -> "ParametrosProceso":
        if self.modo_uv not in ("por_capa", "seguimiento"):
            raise ValueError(f"modo_uv desconocido: {self.modo_uv}")
        if self.estrategia not in ("secuencial", "paralelo"):
            raise ValueError(f"estrategia desconocida: {self.estrategia}")
        if self.modo_uv == "seguimiento" and self.estrategia == "paralelo":
            # El brazo UV sólo puede seguir a un extrusor a la vez.
            return replace(self, estrategia="secuencial")
        return self

    def a_dict(self) -> dict:
        return asdict(self)


# Rangos de búsqueda/muestreo de los parámetros continuos.
RANGOS: dict[str, tuple[float, float]] = {
    "presion_e1_kpa": (40.0, 200.0),
    "presion_e2_kpa": (30.0, 160.0),
    "velocidad_mm_s": (3.0, 20.0),
    "altura_capa_mm": (0.2, 0.45),
    "intensidad_uv_mw_cm2": (5.0, 80.0),
    "velocidad_uv_mm_s": (0.8, 10.0),
    "retardo_uv_s": (0.1, 5.0),
    "fotoiniciador_pct": (0.1, 1.0),
}

PARAMS_CONTINUOS = tuple(RANGOS.keys())
assert set(PARAMS_CONTINUOS) <= {f.name for f in fields(ParametrosProceso)}
