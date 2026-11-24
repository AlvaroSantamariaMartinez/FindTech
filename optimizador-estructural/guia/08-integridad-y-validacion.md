# 8. Integridad estructural y validación

La pregunta del millón: **¿cómo sé que lo que propone la red aguanta?** Este capítulo
explica la cadena de salvaguardas que aplica el proyecto y, con la misma honestidad,
lo que queda fuera de ella.

Código: `toponet/analysis.py`, `toponet/nn/infer.py`, `toponet/plugins/neural_unet.py`.

## 8.1 La cadena de seguridad

```
 red neuronal ─► calibración ─► (refinamiento ─► binarización ─► limpieza de ─► FEM del ─► comprobaciones
   (logits)       de volumen      SIMP, híbrido)   (umbral 0.5)    islas           diseño       e informe
     6.5            6.5               8.2             8.3            8.3          final 8.4      8.5
```

Lo importante: **todos los modelos pasan por la misma validación** (pasos 8.3–8.5),
la ejecuta la aplicación, no el plugin. Un plugin no puede "maquillar" sus métricas.

## 8.2 Modo híbrido: la red propone, la física dispone

Con `refine_iters > 0`, el plugin TopoNet usa la predicción como **punto de partida**
de SIMP (`run_simp(x0=pred)`), empezando con la proyección ya en $\beta$ = 2:

* Si la red acertó, SIMP solo pule bordes (pocos cambios).
* Si la red dejó una barra rota o un miembro innecesario, las sensibilidades del FEM
  lo detectan: la energía de deformación se dispara alrededor del corte y OC añade
  material ahí, quitándolo de donde no trabaja.

El resultado es un **óptimo local físico** (las condiciones de optimalidad de SIMP se
cumplen aproximadamente), algo que la red sola no puede prometer. Con 10–20
iteraciones en lugar de 60–100, el ahorro de tiempo es de 3–6×.

## 8.3 Binarización y limpieza

Lo que se fabrica es 0/1, no densidades grises. La validación:

1. **Binariza** con el umbral (0.5 por defecto) y añade las zonas no diseñables.
2. Etiqueta las **componentes conexas** con conectividad por **caras** (6 vecinos).
   Dos vóxeles que solo se tocan por una arista o un vértice no forman una unión
   resistente (sería una articulación de área cero), por eso no cuentan como conexión.
3. Conserva solo las componentes que tocan algún **apoyo**. El resto son **islas
   flotantes**: no transmiten carga y en una pieza real serían trozos sueltos. Se
   eliminan y se informa de cuántos vóxeles se quitaron.

## 8.4 Análisis FEM del diseño final

Sobre el diseño limpio, con el **material real** (E, ν) y las **cargas reales** (N):

| Métrica | Fórmula | Interpretación |
|---------|---------|----------------|
| Flexibilidad | $c = \mathbf F^\top\mathbf u$ (N·mm) | Menor = más rígida |
| Rigidez conservada | $c_{maciza}/c$ | % de la rigidez original que se mantiene |
| Rigidez/masa | $(c_{maciza}/c)/(V/V_0)$ | > 1: más eficiente que la original |
| Desplazamiento máx. | $\max\|\mathbf u\|$ (mm) | Requisito funcional típico |
| $\sigma_{vm}$ p99 y máx. | MPa | Tensión representativa y pico |
| Factor de seguridad | $\sigma_y/\sigma_{vm,p99}$ | Margen frente a fluencia |
| Masa | $V\rho$ (g) | Lo que ahorras |

**Lectura de la rigidez específica:** quitar el 70 % del material de una pieza
maciza suele conservar el 50–60 % de su rigidez → rigidez/masa ≈ 1.7–2×. Es el
"porqué" de la optimización topológica: el material quitado trabajaba poco.

## 8.5 Comprobaciones (✔/✘ en la WebUI)

| Comprobación | Criterio | Qué significa un ✘ |
|--------------|----------|---------------------|
| **Camino de carga** | > 99.9 % de la carga actúa sobre material conectado a un apoyo | Alguna carga "cae al vacío": la pieza no cumple su función |
| **Sin islas flotantes** | 0 vóxeles eliminados | El modelo dejó material inútil (se ha quitado) |
| **Resistencia** | $FS \geq$ objetivo (1.5 por defecto, configurable) | Plastificaría con la carga × FS: añade material o cambia de material |
| **Solución FEM** | CG converge | Posible mecanismo (pieza que puede girar/deslizar): revisa apoyos |
| **Espesor mínimo** | < 5 % del material en miembros de 1 vóxel | Barras/láminas frágiles y difíciles de fabricar: sube $r_{min}$ o la resolución |

Un miembro "de 1 vóxel" es aquel cuyos dos vecinos en algún eje están vacíos
(`thin_voxels()`); con 2 vóxeles de lado 1 mm, por ejemplo, la boquilla de 0.4 mm
de una impresora FDM ya puede tener problemas para hacerlo bien.

## 8.6 ¿Y si el diseño no cumple?

* **FS bajo:** sube la fracción de volumen; usa un material más resistente; reparte
  mejor la carga (radio mayor); como último recurso, elige un umbral menor (más material).
* **Camino de carga roto (solo red):** activa el refinamiento SIMP; sube la
  resolución; entrena con más datos parecidos a tu caso.
* **Miembros finos:** aumenta $r_{min}$ (SIMP/BESO) o la resolución.
* **FEM no converge:** añade apoyos para impedir los 6 movimientos rígidos.

## 8.7 Limitaciones que debes conocer

> Las comprobaciones de este capítulo son la **validación rápida por vóxeles**, la que
> se aplica a todos los diseños al optimizar. Tiende a ser optimista en resistencia (ver
> [cap. 11.1](11-fisica-realista.md)). Para decidir si una pieza aguanta usa el
> **análisis avanzado** (cap. 11): geometría real, tetraedros cuadráticos, pandeo,
> fatiga, peso propio y capas de impresión.


Este proyecto es una herramienta de **diseño conceptual y aprendizaje**:

1. **Modelo lineal elástico, estático, isótropo.** No contempla pandeo, fatiga,
   impacto, plasticidad, contacto ni anisotropía (impresión 3D, compuestos).
2. **Discretización en vóxeles.** Las tensiones en superficies escalonadas son
   aproximadas; el p99 mitiga pero no elimina el error. El STL suavizado (marching
   cubes) no es exactamente el modelo analizado.
3. **Un caso de carga.** Una pieza real suele tener varios (montaje, uso, transporte):
   ejecuta la optimización para cada uno y combina, o extiende SIMP a multicarga (cap. 4.11).
4. **El objetivo es rigidez, no resistencia.** La resistencia se *comprueba*, no se
   *optimiza*. Con cargas concentradas o esquinas, el FS puede ser bajo aunque la
   rigidez sea excelente.

Para impresión FDM, una regla conservadora es usar un $\sigma_y$ efectivo del 50–60 %
del nominal si la carga tracciona entre capas, y FS ≥ 2.

**Antes de usar una pieza en una aplicación donde su fallo tenga consecuencias,**
reconstruye la geometría en CAD, analízala con software de FEM validado (malla de
tetraedros de segundo orden, convergencia de malla, todos los casos de carga) y
ensaya prototipos.

## 8.8 Validar el propio validador

Los tests (`tests/`) comprueban que las herramientas de validación son correctas:

* FEM frente a la solución analítica de la viga en voladizo (< 2 %).
* La matriz de rigidez tiene 6 modos de sólido rígido.
* Una barra con un corte se detecta como camino de carga roto.
* Las islas se eliminan; un diseño macizo pasa todas las comprobaciones.
* SIMP respeta el volumen y mejora la flexibilidad respecto al diseño uniforme.

```bash
python -m pytest -q
```

---
← [7. Sistema de entrenamiento](07-sistema-entrenamiento.md) · Siguiente: [9. WebUI y plugins →](09-webui-y-plugins.md)
