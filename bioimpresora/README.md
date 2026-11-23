# biosim — Simulador y aprendizaje profundo para bioimpresora de órganos biomiméticos

Gemelo digital de una bioimpresora de extrusión con **4 brazos independientes**:

| Brazo | Herramienta | Función |
|-------|-------------|---------|
| `E1`  | Extrusor neumático 1 (`T0`) | Material **A**: biopolímero estructural + primer fotoiniciador |
| `E2`  | Extrusor neumático 2 (`T1`) | Material **B**: biotinta con células + primer fotoiniciador |
| `UV`  | Guía de luz UV 365 nm (`T2`) | Fotopolimeriza (solidifica) el primer |
| `AUX` | Brazo extra (`T3`) | **Sin uso**: permanece estacionado; reservado para cámara, 3er material, pinza… |

El programa simula la impresión completa (trayectorias, antichoque, reología,
curado UV, deformación, viabilidad celular) y entrena una **red neuronal
profunda** que aprende a predecir la calidad y a encontrar los parámetros de
impresión óptimos (diseño inverso).

Solo necesita **Python ≥ 3.10 y NumPy** (la red neuronal está escrita en NumPy).

## Uso rápido

```bash
cd bioimpresora
python -m biosim info                                   # configuración de la máquina
python -m biosim simular --organo vaso --ver-capa 0     # una impresión
python -m biosim simular --organo lobulo_hepatico --modo-uv seguimiento --gcode lobulo.gcode
python -m biosim dataset --n 4000 --salida datos.npz    # ~30 s con 4 núcleos
python -m biosim entrenar --datos datos.npz --modelo modelo.npz
python -m biosim optimizar --modelo modelo.npz --organo vaso --viabilidad-min 0.85
python -m pytest tests
```

## Arquitectura

```
biosim/
├── config.py        Brazos (E1, E2, UV, AUX) y parámetros de proceso + rangos
├── materiales.py    Biotinta: Herschel-Bulkley, cinética de fotocurado, viabilidad
├── geometria.py     Órganos voxelizados: vaso, lóbulo hepático, parche cardíaco
├── cinematica.py    Trayectorias de los brazos y detección de colisiones
├── planificador.py  Raster 0°/90°, secuenciación de brazos, barrido UV, G-code
├── simulador.py     Curado capa a capa → forma real → métricas
└── ia/
    ├── red.py       Perceptrón multicapa (backprop, Adam, parada temprana, ∂y/∂x)
    ├── datos.py     Generación paralela de datos sintéticos con el simulador
    └── sustituto.py Modelo sustituto + optimización por gradiente (diseño inverso)
```

## Modelos físicos

- **Flujo en la boquilla** (Herschel-Bulkley `τ = τ0 + K·γ̇ⁿ`): presión → caudal → relación
  de extrusión (sub/sobre-extrusión → huecos o ensanchamiento del filamento).
- **Fotocurado**: `dα/dt = k·√(I − I_inh)·(1 − α)` con `k ∝ √[fotoiniciador]` y atenuación
  Beer-Lambert `I(z) = I0·e^(−μz)` a través de las capas superiores (cada pasada también
  cura las capas inferiores y suma dosis).
- **Deformación**: mientras el filamento no alcanza `α_gel` se extiende (slumping), con
  constante de tiempo ligada al esfuerzo umbral. Las capas sin gelificar colapsan.
- **Viabilidad celular** = supervivencia a cizalla en la boquilla × `exp(−dosis UV / D_letal)`.
- **Modos UV**: `por_capa` (el brazo UV barre la capa al terminar) o `seguimiento` (sigue al
  extrusor con un retardo; si el spot queda demasiado cerca de la boquilla hay **riesgo de
  obstrucción** por curado dentro de la punta).
- **Estrategias**: `secuencial` (E1 → E2) o `paralelo` (ambos a la vez; el planificador
  busca el menor retardo de arranque de E2 que evita colisiones entre cabezales).

### Métricas

`fidelidad_iou` (forma impresa vs objetivo), `viabilidad`, `fraccion_curada`,
`conversion_media`, `error_altura`, `tiempo_s`, `riesgo_obstruccion` y una
`puntuacion` global ponderada (editable en `simulador.py`).

## Aprendizaje profundo

1. `dataset`: muestrea aleatoriamente 8 parámetros continuos (presiones, velocidades,
   altura de capa, intensidad UV, retardo, % fotoiniciador) + modo + órgano y simula.
2. `entrenar`: red 14→128→128→64→8 (SiLU, Adam, decaimiento coseno). Con 4000
   muestras alcanza R² ≈ 0.97–0.99 en validación para todas las métricas.
3. `optimizar`: ascenso por gradiente **a través de la red** sobre los parámetros (con
   restricciones opcionales de viabilidad/fidelidad), multi-arranque por modo, y
   validación de los mejores candidatos con el simulador físico.

Resultados de ejemplo (puntuación con parámetros por defecto → optimizados, simulada):
vaso 0.79 → 0.91 · lóbulo hepático 0.77 → 0.89 · parche cardíaco 0.78 → 0.82.

## Limitaciones y próximos pasos

- Los coeficientes de los materiales son verosímiles pero **no están calibrados**: hay que
  ajustarlos con ensayos reales (reometría, fotorreometría, ensayos de viabilidad).
- Modelo térmico, difusión de oxígeno y mecánica del gel están simplificados.
- Ideas: aprendizaje activo (reentrenar con los candidatos validados), visión por
  computador con el brazo `AUX` como cámara para control en lazo cerrado, aprendizaje por
  refuerzo de trayectorias, geometrías desde imágenes médicas (`geometria.desde_array`),
  exportación a PyTorch.
