# 9. TopoNet Studio: la WebUI y el sistema de plugins

## 9.1 Arrancar

```bash
python -m webui.server                 # http://127.0.0.1:8000
python -m webui.server --host 0.0.0.0 --port 8080   # accesible desde tu red local
```

Variables de entorno opcionales:

| Variable | Efecto | Defecto |
|----------|--------|---------|
| `TOPONET_WORKERS` | Modelos que se ejecutan a la vez | 4 |
| `TOPONET_MAX_ELEMENTS` | Límite de elementos por trabajo | 250 000 |
| `TOPONET_PLUGINS` | Carpetas extra de plugins (separadas por `:`) | — |
| `TOPONET_CHECKPOINTS` | Carpeta de checkpoints de la red | `checkpoints/` |

El visor 3D usa three.js desde un CDN (unpkg), así que el navegador necesita
conexión a internet la primera vez (luego queda en caché).

### El ejecutable

`toponet_studio.py` es el punto de entrada único; con PyInstaller
(`empaquetado/toponet_studio.spec`) se convierte en un programa sin dependencias:

```
TopoNetStudio                      # abre la app en el navegador
TopoNetStudio servir --port 8080   # --host, --no-navegador
TopoNetStudio autoprueba           # FEM, SIMP, malla, pandeo, fatiga, red y web
TopoNetStudio generar-datos --n 800 --workers 4
TopoNetStudio entrenar --epochs 80 --out checkpoints/mi_red.pt
TopoNetStudio evaluar --ckpt checkpoints/mi_red.pt --n 40
```

Las carpetas `checkpoints/` y `plugins/` **junto al ejecutable** son tuyas: lo que
pongas ahí aparece en la WebUI. El flujo de GitHub Actions
`.github/workflows/toponet-ejecutables.yml` compila el programa para Windows, Linux y
macOS (Apple Silicon), pasa los tests y la autoprueba, y publica cada uno como
artefacto descargable. El ejecutable entrena en CPU; para GPU entrena desde el código
con PyTorch para CUDA (los `.pt` son compatibles).

## 9.2 Flujo de trabajo

1. **Pieza:** sube tu STL (también OBJ/PLY) o elige un ejemplo. Los ejemplos aplican
   apoyos y cargas razonables automáticamente.
2. **Malla de cálculo:** elige la resolución. "Ver vóxeles" superpone la pieza
   voxelizada en naranja: comprueba que las partes finas tienen ≥ 2–3 vóxeles.
3. **Material:** elige un preset o escribe E, ν, límite elástico y densidad.
4. **Apoyos y cargas:**
   * "＋ Apoyo" / "＋ Carga" y clic sobre la pieza en el visor *Original* → se crea
     una región esférica en ese punto. La carga se orienta por defecto hacia dentro
     de la superficie (normal) con 100 N.
   * "Empotrar cara" / "Cargar cara" usan la cara elegida de la caja envolvente.
   * Edita centro, radio, fuerza (N) y direcciones bloqueadas en cada tarjeta.
     `Esc` cancela el modo de selección.
5. **Objetivo:** % de material a conservar y factor de seguridad exigido.
6. **Modelos:** marca los que quieras comparar y ajusta sus parámetros.
7. **Optimizar.** Cada modelo aparece en su propio visor con barra de progreso.

### Leer los resultados

* Todas las vistas comparten cámara: al girar una, giran todas.
* **Color:** *Material*, *Tensión de von Mises* o *Desplazamiento*. La escala es
  **común a todas las vistas** (el máximo es el p99 más alto), así los colores son
  comparables entre modelos. La vista *Original* muestra las tensiones de la pieza maciza.
* **Silueta original:** muestra la pieza de partida en transparente.
* **Umbral:** desliza para ver la pieza con más (umbral bajo) o menos material; la
  malla y las métricas se recalculan con FEM para ese umbral.
* **Descargar STL:** exporta el diseño con el umbral actual.
* **Tabla de comparación:** en verde, el mejor valor de cada fila entre los modelos.
  Pasa el ratón por ✔/✘ para ver el detalle de cada comprobación (cap. 8).

## 9.3 Arquitectura

```
navegador (static/app.js, three.js)                 servidor (webui/server.py, FastAPI)
──────────────────────────────────                  ──────────────────────────────────────
POST /api/upload | /api/examples/{n}   ───────────► load_mesh() → MESHES[id]
GET  /api/mesh/{id}/stl                ◄─────────── STL reparado (para dibujarlo)
POST /api/voxelize                     ───────────► voxelize() (con caché)
POST /api/jobs {mesh, regiones, material,
                volfrac, modelos[]}    ───────────► hilo del trabajo:
                                                      _build_problem() → Problem
                                                      evaluate(macizo) → referencia
                                                      ThreadPool: plugin.optimize() × N  (en paralelo)
                                                      evaluate(diseño) → métricas + checks
GET  /api/jobs/{id}  (cada 0.8 s)      ◄─────────── estado, progreso, métricas
GET  /api/results/{rid}/mesh?threshold ◄─────────── marching cubes + campos por vértice (base64)
GET  /api/results/{rid}/stl?threshold  ◄─────────── descarga
GET  /api/results/{rid}/density.npz    ◄─────────── densidades crudas para tu post-proceso
GET  /api/models  | POST /api/models/reload ◄────── catálogo de plugins (parámetros incluidos)
POST /api/results/{rid}/advanced       ───────────► análisis avanzado (cap. 11), en cola propia
GET  /api/advanced/{aid}               ◄─────────── progreso, métricas, comprobaciones y malla
GET  /api/physics/info                 ◄─────────── malladores disponibles y fuentes de la física
```

Decisiones de diseño:

* **La validación la hace el servidor**, igual para todos: los plugins solo devuelven
  densidades.
* **Paralelismo con hilos:** NumPy, SciPy y PyTorch liberan el GIL en el cálculo
  pesado, así que los modelos avanzan realmente en paralelo.
* **Mallas en binario (base64 de float32/uint32)** en lugar de listas JSON: 4–5×
  menos datos.
* **Los errores de un modelo no tumban a los demás:** cada uno informa del suyo.
* La documentación interactiva de la API está en `http://localhost:8000/docs`
  (generada por FastAPI): úsala para automatizar optimizaciones desde scripts.

## 9.4 Crear tu propio plugin

Un plugin es una clase con un método `optimize(problem, params, progress)` que
devuelve un array de densidades con la forma de la rejilla. Paso a paso:

**1. Crea `plugins/mi_modelo.py`:**

```python
import numpy as np
from toponet.plugins import OptimizerPlugin, Param, register
from toponet.fem import HexMesh


@register
class MiModelo(OptimizerPlugin):
    id = "mi_modelo"                       # único
    name = "Mi modelo"                     # lo que se ve en la WebUI
    kind = "heurístico"                    # etiqueta libre
    description = "Quita el material con menos energía en un solo paso."
    params = [
        Param("potencia", "float", 1.0, "Potencia", min=0.1, max=3.0, step=0.1,
              help="Exponente aplicado a la energía antes de umbralizar."),
    ]

    def optimize(self, problem, params, progress):
        progress(0.1, "Analizando la pieza maciza…")
        mesh = HexMesh(problem.domain, problem.material.nu, problem.fixed)
        res = mesh.solve(np.full(mesh.n_elements, problem.material.E), problem.pitch, problem.forces)
        score = res.ce ** params["potencia"]
        # conserva los elementos con más energía hasta la fracción de volumen pedida
        n_keep = int(problem.volfrac * problem.n_domain)
        thr = np.sort(score[problem.domain])[::-1][n_keep - 1]
        progress(1.0, "Listo")
        return ((score >= thr) & problem.domain).astype(float)
```

**2.** Pulsa **"recargar"** en la sección *Modelos* (o reinicia el servidor). Tu modelo
aparece con sus parámetros generados automáticamente.

### Qué recibe tu plugin: `Problem`

| Atributo | Tipo | Contenido |
|----------|------|-----------|
| `domain` | bool (nx,ny,nz) | vóxeles de la pieza |
| `passive_solid` | bool (nx,ny,nz) | vóxeles que deben quedar macizos |
| `design` | bool | `domain & ~passive_solid` |
| `fixed` | bool (nx+1,ny+1,nz+1,3) | GDL bloqueados por nodo |
| `forces` | float (nx+1,ny+1,nz+1,3) | fuerza por nodo (N) |
| `material` | `Material` | E, nu, yield_strength, density |
| `volfrac` | float | fracción de volumen objetivo |
| `pitch`, `origin` | float, (3,) | tamaño de vóxel y posición (mm) |

Herramientas reutilizables: `HexMesh` (FEM), `run_simp` (refinamiento),
`DensityFilter`, `build_features` (entrada de la red), `evaluate` (métricas).

### Tipos de parámetro

| `type` | Control en la WebUI | Opciones |
|--------|---------------------|----------|
| `int`, `float` | campo numérico | `min`, `max`, `step` |
| `bool` | casilla | — |
| `choice` | desplegable | `choices=[...]` |

Si los parámetros dependen del entorno (p. ej. una lista de archivos), sobrescribe
`get_params()` (así lo hace el plugin TopoNet con los checkpoints). Si tu plugin
necesita algo que puede faltar (una librería, un archivo de pesos), implementa
`available()` → `(False, "motivo")`: la WebUI lo mostrará desactivado con el motivo.

### Contrato

* Devuelve un `np.ndarray` con forma `problem.shape` y valores en [0, 1].
* Llama a `progress(fracción, mensaje)` de vez en cuando (es opcional pero útil).
* No hace falta respetar exactamente el volumen ni limpiar islas: la validación
  común binariza, limpia y mide. Pero tu modelo será juzgado por ello.
* El código se ejecuta en un hilo: no uses estado global mutable sin un `Lock`.

## 9.5 Integrar otros tipos de modelos

**Otro checkpoint de TopoNet:** copia el `.pt` a `checkpoints/` → aparece en el
desplegable del plugin TopoNet. Puedes comparar dos versiones de tu red marcando el
modelo dos veces... o mejor, crea un plugin mínimo que herede de `NeuralUNet` con
otro `id` y otro checkpoint por defecto.

**Una red con otra arquitectura (PyTorch):** en tu plugin, carga el modelo una vez
(caché), construye la entrada con `build_features(problem)` o con tu propia
codificación, y aplica `calibrate_volume()` a la salida.

**Un modelo ONNX** (exportado desde TensorFlow, JAX, etc.):

```python
import onnxruntime as ort
from toponet.nn.features import build_features
from toponet.nn.infer import calibrate_volume

class ModeloONNX(OptimizerPlugin):
    ...
    def optimize(self, problem, params, progress):
        sess = ort.InferenceSession("checkpoints/mi_red.onnx")
        x = build_features(problem)[None].astype("float32")
        logits = sess.run(None, {"input": x})[0][0, 0]
        return calibrate_volume(logits.astype(float), problem)
```

(Exportar TopoNet a ONNX: `torch.onnx.export(model, x, "toponet.onnx",
dynamic_axes={"input": {2: "X", 3: "Y", 4: "Z"}})`.)

**Un servicio remoto (HTTP):** envía `domain`, `fixed`, `forces`... (por ejemplo como
`.npz`) a tu servidor de inferencia con `requests` y devuelve las densidades. Útil si
tu red necesita una GPU que no está en la máquina de la WebUI.

**Un optimizador comercial o externo:** exporta el problema a su formato (p. ej. un
archivo de entrada de un solver FEM), ejecútalo con `subprocess` y vuelve a leer la
densidad. La comparación con los demás modelos se hace igual.

---
← [8. Integridad y validación](08-integridad-y-validacion.md) · Siguiente: [10. Referencias y siguientes pasos →](10-referencias-y-siguientes-pasos.md)
