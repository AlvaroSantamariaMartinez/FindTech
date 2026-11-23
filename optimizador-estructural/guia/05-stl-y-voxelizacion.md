# 5. Del STL a los vóxeles (y vuelta)

Código: `toponet/geometry.py`, `toponet/problem.py`, `examples/generate_examples.py`.

## 5.1 El formato STL

Un STL es una lista de triángulos, cada uno con 3 vértices y una normal:

```
solid pieza                         ← STL ASCII (el binario guarda lo mismo:
  facet normal 0 0 1                   cabecera 80 B + nº triángulos + 50 B/triángulo)
    outer loop
      vertex 0 0 10
      vertex 10 0 10
      vertex 0 10 10
    endloop
  endfacet
  ...
endsolid
```

Lo que **no** tiene: unidades (asumimos mm), conectividad (los vértices compartidos
se repiten), interior (solo la "piel"), información de material.

Para poder hablar de "dentro" y "fuera" la malla debe ser **estanca** (*watertight*):
cerrada, sin agujeros, cada arista compartida por exactamente 2 triángulos y con las
normales hacia fuera. `load_mesh()` aplica reparaciones básicas con `trimesh`:

* fusiona vértices duplicados,
* elimina triángulos degenerados (área 0) y repetidos,
* rellena agujeros pequeños,
* reorienta las normales de forma consistente.

Si tu STL sigue sin ser estanco, la WebUI lo avisa; repáralo antes con
herramientas como Meshmixer, PrusaSlicer ("reparar"), Blender (*3D Print Toolbox*)
o `trimesh`/`pymeshfix`.

## 5.2 Rejilla de cálculo

`grid_for_mesh()` decide la rejilla a partir de un único parámetro, la
**resolución** = nº de vóxeles en el eje más largo de la pieza:

$$
h = \frac{\max(L_x, L_y, L_z)}{\text{resolución}},\qquad n_i = \left\lceil \frac{L_i}{h}\right\rceil
$$

La rejilla se centra sobre la caja envolvente. Cada vóxel es un elemento H8 de lado $h$.

**Compromiso resolución/coste:** duplicar la resolución multiplica por 8 los
elementos y por ~10 el tiempo del FEM. Además, el espesor mínimo de los miembros es
≈ $2 r_{min} h$: una resolución baja produce barras gruesas. Recomendaciones:

| Uso | Resolución |
|-----|-----------|
| Exploración rápida | 24–32 |
| Diseño conceptual | 40–56 |
| Detalle (paciencia) | 64–96 |

Asegúrate de que las partes más finas de la pieza tengan al menos 2–3 vóxeles de
grosor (usa "Ver vóxeles" en la WebUI).

## 5.3 Voxelización por paridad de rayos

¿Está el centro de un vóxel dentro de la malla? Teorema de la curva de Jordan en
3D: lanza un rayo desde el punto; si cruza la superficie un número **impar** de veces,
está dentro.

En lugar de lanzar un rayo por vóxel, `_parity_fill()` lanza **un rayo por columna**
(paralelo a un eje, p. ej. z) y calcula todos sus cruces de una vez:

1. Para cada triángulo, se enumeran las columnas $(i,j)$ cuyo centro cae dentro de
   la caja envolvente de su proyección en el plano xy.
2. Test **baricéntrico** 2D: el punto $(x_c, y_c)$ está dentro del triángulo
   proyectado si sus tres coordenadas baricéntricas son ≥ 0. Si lo está, la altura del
   cruce es $z = \lambda_0 z_0 + \lambda_1 z_1 + \lambda_2 z_2$.
3. Cada cruce suma 1 en un contador en la posición del primer centro de vóxel por
   encima de $z$.
4. La **suma acumulada** a lo largo de la columna, módulo 2, dice si cada centro está
   dentro (impar) o fuera (par).

Todo está vectorizado con NumPy (sin bucles de Python por triángulo) y procesado por
bloques para acotar memoria: un STL de 50 000 triángulos se voxeliza en ~30 ms.

**Robustez:**

* Un rayo que pasa exactamente por una arista o un vértice contaría dos cruces. Se
  desplazan los rayos una cantidad minúscula e "irracional" (`jitter`).
* Se repite el proceso en los **3 ejes** y se vota por mayoría (≥ 2 de 3): un pequeño
  agujero en la malla solo estropea las columnas de un eje.
* Si aun así no sale nada (malla muy rota), se recurre a la voxelización de
  superficie de `trimesh` + relleno.

**Verificación:** el volumen voxelizado del soporte en L (resolución 40) difiere un
0.2 % del volumen exacto de la malla; el de la viga, 0.0 %.

## 5.4 Del clic del usuario a las condiciones de contorno

La WebUI trabaja en coordenadas del STL (mm). Cada apoyo o carga es una `Region`:

| Forma | Parámetros | Nodos seleccionados |
|-------|------------|---------------------|
| `sphere` | centro, radio | nodos activos a distancia ≤ radio del centro |
| `face` | `xmin`…`zmax` | nodos activos en el plano extremo de la caja de la pieza |

`apply_regions()` convierte cada región en:

* **Apoyo:** bloquea los GDL elegidos (x, y, z) de esos nodos. Bloquear solo algunos
  modela un apoyo deslizante (p. ej. un rodillo: solo z).
* **Carga:** reparte la fuerza total (N) entre los nodos: $\mathbf f_i = \mathbf F/n$.
* **Zona no diseñable** (opcional, activada por defecto): los elementos que tocan
  esos nodos quedan macizos.

Solo se consideran nodos **activos** (que pertenecen a algún vóxel de la pieza). Si
la esfera es más pequeña que un vóxel, se toma el nodo activo más cercano.

**Buenas prácticas:**

* Modela un tornillo como una esfera del tamaño de la cabeza/arandela alrededor del
  taladro, bloqueando x, y, z.
* Reparte las cargas en una zona realista (la superficie de contacto), no en un punto.
* Los apoyos deben impedir los 6 movimientos rígidos. Un único apoyo esférico
  pequeño deja la pieza "pivotando": el validador lo detectaría como fallo del FEM.

## 5.5 Vuelta a STL: marching cubes

El optimizador devuelve densidades por vóxel. Para obtener una superficie,
`density_to_mesh()` extrae la **isosuperficie** $\rho = $ umbral (0.5 por defecto)
con el algoritmo **marching cubes** (Lorensen & Cline 1987):

1. Se considera cada cubo formado por 8 centros de vóxel vecinos.
2. Según cuáles estén por encima del umbral (256 casos, 15 únicos por simetría), se
   colocan triángulos con vértices interpolados linealmente en las aristas.

Con densidades continuas (SIMP, red neuronal) la interpolación produce superficies
mucho más suaves que los "escalones" de los vóxeles. Después:

* **Suavizado de Taubin** (Taubin 1995): alterna un paso de suavizado laplaciano
  ($\lambda$ = 0.5) con uno de "inflado" ($\mu$ = −0.53), lo que suaviza sin encoger la
  pieza (el laplaciano puro la encoge en cada iteración).
* Se rellena con un vóxel vacío alrededor para que la malla salga **cerrada**.

El **umbral** de la WebUI permite ver cómo cambia la pieza al ser más o menos
conservador: un umbral bajo (0.3) incluye las zonas grises (más material, más
rígida); uno alto (0.7) solo lo más seguro. Las métricas se recalculan para cada umbral.

## 5.6 Del diseño a la pieza fabricable

El STL resultante es un **diseño conceptual**. Flujo recomendado:

1. Descarga el STL desde la WebUI (o la densidad `.npz` para tu propio post-proceso).
2. Importa en tu CAD como referencia y **remodela** con geometría limpia (o usa
   herramientas de reconstrucción tipo *T-splines*/*SubD*).
3. Re-analiza con un FEM de calidad (tetraedros cuadráticos) y cargas reales.
4. Para impresión 3D directa: revisa voladizos, espesores mínimos de la boquilla y
   la orientación (anisotropía entre capas).

---
← [4. Optimización topológica](04-optimizacion-topologica.md) · Siguiente: [6. Redes neuronales →](06-redes-neuronales.md)
