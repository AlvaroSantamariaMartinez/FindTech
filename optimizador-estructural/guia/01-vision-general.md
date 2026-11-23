# 1. Visión general y arquitectura

## 1.1 El problema que queremos resolver

Tienes una pieza (un soporte, una brida, una viga...) en formato STL. Sabes:

* **dónde se sujeta** (tornillos, superficies apoyadas, empotramientos): los *apoyos*;
* **qué fuerzas recibe** y en qué dirección: las *cargas*;
* **de qué material** está hecha;
* **cuánto material quieres ahorrar** (p. ej. quedarte con el 30 %).

Quieres obtener una pieza nueva, contenida dentro de la original, que use menos
material pero siga cumpliendo su función:

| Cualidad | Qué significa | Cómo se mide en este proyecto |
|----------|---------------|-------------------------------|
| **Integridad estructural** | La pieza es una sola estructura conectada que lleva cada carga hasta los apoyos | Camino de carga (% de carga transmitida), ausencia de islas |
| **Rigidez** | Se deforma poco bajo carga | Flexibilidad $c = \mathbf F^\top\mathbf u$, desplazamiento máximo |
| **Resistencia** | El material no plastifica ni rompe | Tensión de von Mises frente al límite elástico |
| **Capacidad de carga** | Carga máxima que soporta con margen | Factor de seguridad $FS = \sigma_y / \sigma_{vm}$ |
| **Eficiencia** | Rigidez por unidad de masa | Rigidez específica relativa a la pieza maciza |
| **Fabricabilidad** | Se puede imprimir/mecanizar | Proporción de miembros de 1 vóxel de grosor |

Este problema se llama **optimización topológica**: no solo cambiamos espesores o
dimensiones (optimización paramétrica) ni solo el contorno (optimización de forma),
sino *dónde hay material y dónde no*, lo que permite crear agujeros y barras nuevas.

```
 Optimización paramétrica     Optimización de forma        Optimización topológica
 ┌──────────────┐             ┌──────────────┐             ┌──────────────┐
 │██████████████│ espesor t   │██████▀▀▀▀▀███│ contorno    │█▀▄  ▄▀█▀▄  ▄▀│ material
 │██████████████│ → t'        │████▄▄▄▄▄▄████│ se deforma  │█  ▀█   █  ▀█ │ donde hace
 └──────────────┘             └──────────────┘             └──────────────┘ falta
```

## 1.2 ¿Por qué una red neuronal?

El método clásico (SIMP, capítulo 4) funciona muy bien pero es **iterativo**: necesita
de 50 a 300 análisis por elementos finitos (FEM). En 3D, con cientos de miles de
elementos, eso son minutos u horas.

Una red neuronal entrenada con miles de soluciones de SIMP puede **aprender la
relación** "problema → estructura óptima" y responder en milisegundos. El precio:

* hay que **generar datos** (cuesta lo mismo que miles de optimizaciones SIMP);
* la red **no garantiza** nada físico: puede producir barras rotas o grosores
  imposibles. Por eso este proyecto la combina con física (modo híbrido + validación).

Una revisión crítica muy recomendable (Woldseth et al., 2022) concluye que muchas
redes publicadas no superan a los métodos clásicos si se cuenta todo el coste. Los
usos en los que **sí** aportan valor, y que este proyecto implementa, son:

1. **Predicción instantánea** para explorar diseños (muchas variantes rápidamente).
2. **Arranque en caliente (warm start)**: la red da un diseño inicial excelente y
   unas pocas iteraciones físicas lo refinan → mismo resultado que SIMP con una
   fracción de las iteraciones.

## 1.3 Arquitectura del sistema

```
                ┌──────────────────────── TopoNet Studio (WebUI) ───────────────────────┐
                │  navegador (three.js)            servidor (FastAPI)                    │
 STL ──────────►│  visor 3D, clics para    ──►  voxelizar ─► Problem ─► plugins en       │
                │  apoyos/cargas, tabla         (geometry)   (problem)   PARALELO        │
                │  comparativa         ◄──  malla + tensiones ◄─ validación FEM común    │
                └───────────────────────────────────────────────────────────────────────┘
                                                           │
           ┌───────────────────────────────────────────────┼──────────────────────────┐
           ▼                        ▼                      ▼                          ▼
   SIMP clásico (base)      TopoNet U-Net 3D        BESO (plugin ejemplo)      tus plugins
   toponet/simp.py          toponet/nn/*            plugins/eso_ejemplo.py     plugins/*.py
           │                        ▲
           │   genera etiquetas     │ entrena
           └──► dataset ────────────┘
               (toponet/nn/dataset.py, train.py)

   Todo se apoya en:  toponet/fem.py (elementos finitos)  y  toponet/analysis.py (validación)
```

### Mapa del código

| Archivo | Papel | Capítulo |
|---------|-------|----------|
| `toponet/problem.py` | Definición del problema (dominio, apoyos, cargas, material) | 1, 5 |
| `toponet/fem.py` | Elementos finitos hexaédricos 3D + solvers | 3 |
| `toponet/simp.py` | Optimizador SIMP (modelo base y generador de datos) | 4 |
| `toponet/geometry.py` | STL ↔ vóxeles, marching cubes | 5 |
| `toponet/nn/features.py` | Codificación del problema como tensor | 6 |
| `toponet/nn/model.py` | Red U-Net 3D | 6 |
| `toponet/nn/dataset.py`, `generate_data.py` | Generación del dataset | 7 |
| `toponet/nn/losses.py`, `train.py` | Pérdidas y bucle de entrenamiento | 7 |
| `toponet/nn/evaluate.py` | Validación física del modelo | 7, 8 |
| `toponet/nn/infer.py` | Inferencia y calibración de volumen | 6, 8 |
| `toponet/analysis.py` | Comprobaciones de integridad y métricas | 8 |
| `toponet/plugins/` | Sistema de plugins + SIMP + TopoNet | 9 |
| `plugins/eso_ejemplo.py` | Plugin externo de ejemplo (BESO) | 4, 9 |
| `webui/` | Servidor y cliente web | 9 |

## 1.4 Representación elegida: vóxeles

Una malla STL es una "piel" de triángulos: no tiene interior. Para razonar sobre
material necesitamos un **volumen**. La opción más sencilla y la que mejor encaja con
redes convolucionales es una **rejilla de vóxeles** (píxeles 3D):

* cada vóxel es un elemento finito hexaédrico (cubo) → FEM directo;
* cada vóxel tiene una **densidad** $\rho \in [0,1]$ (0 = vacío, 1 = material);
* una red convolucional 3D procesa la rejilla igual que una red 2D procesa una imagen.

Las alternativas (mallas de tetraedros, nubes de puntos, grafos, funciones
implícitas) se comentan en el capítulo 6; son más flexibles pero bastante más
complejas de implementar y de entrenar.

## 1.5 Instalación

```bash
cd optimizador-estructural
python -m venv .venv && source .venv/bin/activate      # opcional pero recomendable
pip install -r requirements.txt
# PyTorch: elige la variante para tu hardware en https://pytorch.org
#   solo CPU:  pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pytest -q                                      # comprueba que todo funciona
```

Requisitos: Python ≥ 3.10. Una GPU acelera el entrenamiento, pero todo el proyecto
(incluido el modelo preentrenado incluido) se ha entrenado en una CPU de 4 núcleos.

## 1.6 Unidades

Todo el proyecto usa **mm, N y MPa** (1 MPa = 1 N/mm²). Con estas unidades los
desplazamientos salen en mm, las tensiones en MPa y la flexibilidad en N·mm. Los
STL no llevan unidades: se asume que están en milímetros (lo habitual en CAD e
impresión 3D).

---
Siguiente: [2. Mecánica estructural →](02-mecanica-estructural.md)
