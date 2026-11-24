# TopoNet Studio · Optimización estructural con redes neuronales

Aligera piezas STL conservando su integridad estructural, rigidez y capacidad de
carga, con una **red neuronal 3D** entrenada por ti, un **optimizador topológico
clásico** de referencia y una **WebUI** para comparar en paralelo cualquier modelo.

```
STL ─► vóxeles ─► apoyos y cargas ─►┬─ SIMP clásico (modelo base) ──┐
                                     ├─ TopoNet U-Net 3D (tu red) ───┼─► validación FEM común ─► STL optimizado
                                     └─ tus plugins (BESO, ONNX…) ───┘   (camino de carga, FS, rigidez…)
```

## ⬇️ El ejecutable

No hace falta instalar Python: descarga el programa de tu sistema de la pestaña
**Actions** del repositorio (flujo *TopoNet Studio · ejecutables*, sección
*Artifacts*), descomprímelo y abre `TopoNetStudio` (`TopoNetStudio.exe` en Windows).
Incluye la WebUI, la física avanzada, el modelo preentrenado y los comandos de
entrenamiento (`TopoNetStudio entrenar ...`). Instrucciones en
[`empaquetado/LEEME.txt`](empaquetado/LEEME.txt).

Para compilarlo tú: `pip install -r requirements.txt pyinstaller` y
`pyinstaller empaquetado/toponet_studio.spec`.

## 🔬 Física realista

Además de la validación rápida por vóxeles, cada diseño (y la pieza original) puede
pasar un **análisis avanzado** sobre su geometría real: tetraedros cuadráticos
(scikit-fem + fTetWild), peso propio, **pandeo** (Bleyer, *Numerical Tours*),
**frecuencias naturales**, **fatiga** (fatpack: Basquin + Goodman) y **anisotropía de
impresión 3D** con criterio de delaminación. Toda la física procede de proyectos
establecidos y está validada contra soluciones analíticas (`tests/test_physics.py`).
Ver el [capítulo 11](guia/11-fisica-realista.md).

## 📘 La guía

La carpeta [`guia/`](guia/README.md) es un curso completo en español con toda la
teoría y su implementación:

1. [Visión general y arquitectura](guia/01-vision-general.md)
2. [Mecánica estructural](guia/02-mecanica-estructural.md)
3. [Método de los elementos finitos](guia/03-elementos-finitos.md)
4. [Optimización topológica (SIMP, BESO)](guia/04-optimizacion-topologica.md)
5. [Del STL a los vóxeles y vuelta](guia/05-stl-y-voxelizacion.md)
6. [Redes neuronales para optimización estructural](guia/06-redes-neuronales.md)
7. [El sistema de entrenamiento](guia/07-sistema-entrenamiento.md)
8. [Integridad estructural y validación](guia/08-integridad-y-validacion.md)
9. [La WebUI y el sistema de plugins](guia/09-webui-y-plugins.md)
10. [Referencias, ejercicios y siguientes pasos](guia/10-referencias-y-siguientes-pasos.md)
11. [Física realista: el análisis avanzado](guia/11-fisica-realista.md)

## Instalación

```bash
cd optimizador-estructural
pip install -r requirements.txt          # PyTorch CPU: ver comentario en requirements.txt
python examples/generate_examples.py     # (re)genera los STL de ejemplo
python -m pytest -q                      # 23 tests: FEM, SIMP, geometría, física avanzada, red, API
```

## Usar la aplicación

```bash
python toponet_studio.py      # → http://127.0.0.1:8000  (o: python -m webui.server)
```

1. Sube un STL (o elige un ejemplo: ya trae apoyos y cargas).
2. Haz clic sobre la pieza para colocar **apoyos** y **cargas** (o usa las caras).
3. Elige material, % de material a conservar y factor de seguridad.
4. Marca los modelos a comparar y pulsa **Optimizar**.
5. Compara en 3D (tensión de von Mises, desplazamientos), ajusta el umbral y
   descarga el STL.

## Entrenar tu red

```bash
python -m toponet.nn.generate_data --n 800 --workers 4      # dataset con SIMP
python -m toponet.nn.train --epochs 80                      # → checkpoints/toponet_unet.pt
python -m toponet.nn.evaluate --n 40 --refine 10            # validación FISICA (FEM)
```

Se incluye un checkpoint preentrenado (`checkpoints/toponet_unet.pt`) para que la
app funcione desde el primer momento; su ficha de resultados está en
[`checkpoints/README.md`](checkpoints/README.md).

## Añadir modelos

Copia [`plugins/eso_ejemplo.py`](plugins/eso_ejemplo.py) y adáptalo: cualquier clase
con `@register` que devuelva densidades aparece en la WebUI con sus parámetros.
Detalles en el [capítulo 9](guia/09-webui-y-plugins.md).

## Estructura

```
toponet/            biblioteca
  problem.py        definición del problema (dominio, apoyos, cargas, material)
  fem.py            elementos finitos H8 + multigrid algebraico
  simp.py           optimización topológica SIMP (modelo base)
  geometry.py       STL ↔ vóxeles, marching cubes
  analysis.py       validación rápida: camino de carga, islas, FS, rigidez, espesor
  physics/          física avanzada: tetraedros P2, pandeo, modos, fatiga, impresión 3D
  nn/               red neuronal: features, model, dataset, losses, train, evaluate, infer
  plugins/          sistema de plugins + SIMP + TopoNet
plugins/            plugins de usuario (ejemplo: BESO)
webui/              servidor FastAPI + cliente three.js
examples/           STL de ejemplo
checkpoints/        pesos entrenados
guia/               la guía
tests/              tests (incluida la validación física contra soluciones analíticas)
toponet_studio.py   punto de entrada (app + comandos de entrenamiento)
empaquetado/        receta de PyInstaller y LEEME del ejecutable
```

> ⚠️ Herramienta educativa y de diseño conceptual. Modelo elástico lineal, estático e
> isótropo: no sustituye a un análisis de ingeniería profesional ni a ensayos
> (ver [capítulo 8](guia/08-integridad-y-validacion.md)).
