# Guía: redes neuronales para optimizar estructuras a partir de un STL

Esta guía te lleva desde cero hasta tener:

1. **Una red neuronal 3D** que, dada una pieza (STL), sus apoyos, sus cargas y la
   cantidad de material que quieres conservar, propone una estructura aligerada que
   mantiene la integridad estructural, la rigidez y la capacidad de carga.
2. **El sistema completo para entrenarla**: generación de datos con física,
   funciones de pérdida, bucle de entrenamiento, validación física y diagnóstico.
3. **Una aplicación web** (TopoNet Studio) para usar tu modelo, ver en 3D cómo cambia
   el STL y compararlo en paralelo con otros modelos (incluido un optimizador clásico
   de base y cualquier plugin que añadas).

Toda la teoría está conectada con código real y ejecutable de este repositorio:
cada capítulo indica qué archivo implementa lo que se explica.

## Índice

| # | Capítulo | Qué aprenderás |
|---|----------|----------------|
| 1 | [Visión general y arquitectura](01-vision-general.md) | El problema, los enfoques posibles y cómo encaja cada pieza del sistema |
| 2 | [Mecánica estructural](02-mecanica-estructural.md) | Tensión, deformación, rigidez, resistencia, von Mises, factor de seguridad |
| 3 | [Método de los elementos finitos](03-elementos-finitos.md) | Cómo se calcula la respuesta de una pieza: el "juez" físico de todo |
| 4 | [Optimización topológica](04-optimizacion-topologica.md) | SIMP, sensibilidades, filtros, proyección, OC, BESO: el modelo de base |
| 5 | [Del STL a los vóxeles y vuelta](05-stl-y-voxelizacion.md) | Formato STL, voxelización, condiciones de contorno, marching cubes |
| 6 | [Redes neuronales para optimización estructural](06-redes-neuronales.md) | Fundamentos, CNN 3D, U-Net, enfoques del estado del arte, diseño de TopoNet |
| 7 | [El sistema de entrenamiento](07-sistema-entrenamiento.md) | Datos, aumentación, pérdidas, optimizador, métricas, diagnóstico, experimentos |
| 8 | [Integridad estructural y validación](08-integridad-y-validacion.md) | Cómo garantizar que lo que propone la red aguanta de verdad |
| 9 | [La WebUI y el sistema de plugins](09-webui-y-plugins.md) | Usar la app, su API y cómo añadir tus propios modelos |
| 10 | [Referencias, ejercicios y siguientes pasos](10-referencias-y-siguientes-pasos.md) | Bibliografía comentada y hoja de ruta para mejorar tu modelo |

## Ruta de aprendizaje recomendada

```
Semana 1  Cap. 1-3   Física y FEM.        Práctica: valida el FEM con la viga en voladizo.
Semana 2  Cap. 4-5   SIMP y geometría.    Práctica: optimiza los STL de ejemplo con SIMP en la WebUI.
Semana 3  Cap. 6     Redes neuronales.    Práctica: lee toponet/nn/model.py y cuenta sus parámetros.
Semana 4  Cap. 7     Entrenamiento.       Práctica: genera 800 muestras y entrena tu primer modelo.
Semana 5  Cap. 8-9   Validación y app.    Práctica: compara tu red con SIMP y crea un plugin propio.
Semana 6+ Cap. 10    Mejoras.             Práctica: ablaciones, más datos, pérdida física, GPU.
```

## Puesta en marcha rápida

```bash
cd optimizador-estructural
pip install -r requirements.txt
python examples/generate_examples.py            # STL de ejemplo
python -m toponet.nn.generate_data --n 800      # dataset (≈ 40 min con 4 núcleos)
python -m toponet.nn.train --epochs 60          # entrena tu red
python -m toponet.nn.evaluate --n 30            # validación física
python -m webui.server                           # http://localhost:8000
```

> **Nota de seguridad.** Este proyecto es una herramienta de aprendizaje y de diseño
> conceptual. Ninguna red neuronal (ni ningún optimizador) sustituye a un análisis
> de ingeniería profesional ni a ensayos cuando una pieza puede poner en riesgo a
> personas o bienes. El capítulo 8 explica exactamente qué se comprueba y qué no.
