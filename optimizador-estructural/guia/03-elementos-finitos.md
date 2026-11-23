# 3. El método de los elementos finitos (FEM)

El FEM convierte las ecuaciones de equilibrio (que tienen infinitas incógnitas, una
por punto) en un sistema lineal $\mathbf K\mathbf u = \mathbf F$ con un número finito
de incógnitas. En este proyecto el FEM es **el juez**: genera las etiquetas del
dataset (vía SIMP), calcula los rasgos físicos de la red y valida cualquier diseño.

Código: `toponet/fem.py`.

## 3.1 Forma débil (principio de los trabajos virtuales)

Multiplicando el equilibrio por un desplazamiento "virtual" $\delta\mathbf u$ que
respeta los apoyos e integrando por partes:

$$
\int_\Omega \delta\boldsymbol\varepsilon^\top \mathbf D\,\boldsymbol\varepsilon\; dV \;=\; \int_{\Gamma_t}\delta\mathbf u^\top \mathbf t\; dA \qquad \forall\,\delta\mathbf u
$$

"El trabajo interno virtual iguala al trabajo externo virtual". Esta forma solo
exige derivadas primeras de $\mathbf u$, lo que permite aproximarlo con funciones
sencillas a trozos.

## 3.2 Discretización con hexaedros de 8 nodos (H8)

Dividimos la pieza en cubos (nuestros vóxeles). Cada cubo tiene 8 nodos con 3
desplazamientos cada uno → **24 grados de libertad (GDL)** por elemento.

Dentro de cada cubo, el desplazamiento se interpola desde los nodos con funciones
de forma trilineales. En coordenadas naturales $(\xi,\eta,\zeta)\in[-1,1]^3$:

$$
N_i(\xi,\eta,\zeta) = \tfrac18 (1+\xi_i\xi)(1+\eta_i\eta)(1+\zeta_i\zeta),\qquad i=1..8
$$

donde $(\xi_i,\eta_i,\zeta_i)$ son las esquinas $(\pm1,\pm1,\pm1)$ (`NODE_SIGNS` en el código).

Cada $N_i$ vale 1 en su nodo y 0 en los demás, y suman 1 en todo el elemento. Así:

$$
\mathbf u(\xi,\eta,\zeta) = \sum_{i=1}^{8} N_i\,\mathbf u_i
$$

## 3.3 Matriz deformación-desplazamiento B

Derivando la interpolación obtenemos la deformación en función de los 24 GDL:

$$
\boldsymbol\varepsilon = \mathbf B\,\mathbf u_e,\qquad \mathbf B\in\mathbb R^{6\times24}
$$

Para el nodo $i$, su bloque de 3 columnas es:

$$
\mathbf B_i = \begin{bmatrix}
\partial_x N_i & 0 & 0\\ 0 & \partial_y N_i & 0\\ 0&0&\partial_z N_i\\
\partial_y N_i & \partial_x N_i & 0\\ 0 & \partial_z N_i & \partial_y N_i\\ \partial_z N_i & 0 & \partial_x N_i
\end{bmatrix}
$$

Como nuestros elementos son cubos perfectos de lado $h$, el jacobiano es trivial:
$\partial/\partial x = (2/h)\,\partial/\partial\xi$ y $\det\mathbf J = (h/2)^3$.

## 3.4 Matriz de rigidez del elemento

Sustituyendo en la forma débil, la contribución de un elemento es:

$$
\mathbf K_e = \int_{\Omega_e}\mathbf B^\top\mathbf D\,\mathbf B\; dV
= \int_{-1}^{1}\!\!\int_{-1}^{1}\!\!\int_{-1}^{1}\mathbf B^\top\mathbf D\,\mathbf B\,\det\mathbf J\; d\xi\,d\eta\,d\zeta
$$

La integral se calcula con **cuadratura de Gauss 2×2×2**: evaluar en los 8 puntos
$(\pm1/\sqrt3,\pm1/\sqrt3,\pm1/\sqrt3)$ con peso 1, que es exacta para este integrando
polinómico.

**Truco de eficiencia:** como $\mathbf B\propto 1/h$ y $\det\mathbf J\propto h^3$,
resulta $\mathbf K_e \propto E\,h$. Calculamos **una sola vez** la matriz del cubo
unidad con $E=1$ (`element_stiffness()`) y la escalamos: $\mathbf K_e = E_e\,h\,\mathbf K_e^0$.
Esto es lo que hace posible variar la densidad elemento a elemento sin recalcular nada.

### Comprobación de cordura

$\mathbf K_e^0$ debe ser simétrica y tener exactamente **6 autovalores nulos**: los 6
movimientos de sólido rígido no almacenan energía. Puedes comprobarlo:

```python
import numpy as np
from toponet.fem import element_stiffness
KE = element_stiffness(0.3)
print(np.sort(np.linalg.eigvalsh(KE))[:7])   # 6 ≈ 0 y el 7.º > 0
```

## 3.5 Ensamblaje

La matriz global $\mathbf K$ suma las contribuciones de todos los elementos en las
posiciones de sus GDL globales. Cada elemento aporta 24×24 = 576 entradas.

En `HexMesh`:

1. `edof` (ne × 24) guarda los índices globales de los GDL de cada elemento.
2. El **patrón disperso** (qué entradas de $\mathbf K$ son no nulas) se calcula **una
   única vez** con `np.unique`. Se guarda para cada una de las 576·ne contribuciones
   su posición en el vector de datos de la matriz CSR.
3. En cada iteración de la optimización solo cambian los $E_e$: el ensamblaje es un
   simple `np.bincount` (≈ 10× más rápido que reconstruir la matriz).

Solo se ensamblan los elementos **activos** (dentro de la pieza): un STL que ocupa
el 30 % de su caja envolvente solo cuesta ese 30 %.

## 3.6 Condiciones de contorno

* **Apoyos:** los GDL bloqueados se eliminan del sistema (se resuelve solo para los
  libres, $\mathbf K_{ff}\mathbf u_f = \mathbf F_f$).
* **Cargas:** la fuerza total de cada región se reparte a partes iguales entre sus
  nodos (`apply_regions()` en `toponet/problem.py`).

Las cargas puntuales en un único nodo crean singularidades (cap. 2.7). Es mejor
repartir la carga en una pequeña zona: la WebUI usa esferas con un radio.

## 3.7 Resolver K u = F

$\mathbf K$ es simétrica, definida positiva (si hay apoyos suficientes) y muy dispersa
(≈ 81 entradas no nulas por fila en 3D). Con $n$ GDL:

| Método | Memoria | Tiempo | Cuándo |
|--------|---------|--------|--------|
| Directo (LU/Cholesky) | crece mucho por el *fill-in* en 3D | rápido para $n$ pequeño | $n$ < ~3 000 |
| Gradiente conjugado (CG) | $O(n)$ | depende del condicionamiento | nunca solo |
| **CG + multigrid algebraico (AMG)** | $O(n)$ | casi $O(n)$ | **por defecto** |

**¿Por qué el directo escala mal en 3D?** La factorización rellena huecos de la
matriz (*fill-in*). Medido en este proyecto: 53 000 GDL → 15–33 s con SuperLU frente a
3.5 s con AMG-CG. El orden de las columnas importa: `permc_spec="MMD_AT_PLUS_A"`
(mínimo grado simétrico) es 2× más rápido que el predeterminado.

**Gradiente conjugado.** Método iterativo para sistemas simétricos definidos
positivos. Su convergencia depende del número de condición $\kappa(\mathbf K)$, que
en optimización topológica es enorme: hay elementos con $E$ = 1 y otros con
$E = 10^{-6}$ (vacío). Sin precondicionador necesitaría miles de iteraciones.

**Multigrid algebraico de agregación suavizada** (`pyamg`). Idea: los errores "suaves"
(de longitud de onda larga) que CG tarda en eliminar se resuelven en una versión
reducida del problema, que a su vez se reduce, etc. Como precondicionador de CG
consigue convergencia en ~10–70 iteraciones independientemente del tamaño. Dos
detalles de implementación que marcan la diferencia:

1. Le pasamos los **6 modos de sólido rígido** (`rigid_body_modes_dofs`): es el
   "núcleo" del operador de elasticidad y la agregación los necesita para construir
   buenos niveles gruesos.
2. Resolver el nivel más grueso con **LU disperso** (`coarse_solver="splu"`), no con
   la pseudoinversa densa por defecto, que llegaba a costar 1.4 s por iteración.

**Arranque en caliente.** En la optimización, el desplazamiento de la iteración
anterior es una excelente estimación inicial para CG (`x0=u_prev`).

## 3.8 Post-proceso: tensiones

Una vez conocido $\mathbf u$, en el centro de cada elemento ($\xi=\eta=\zeta=0$):

$$
\boldsymbol\sigma_e = E_e\,\mathbf D^0\,\mathbf B(0,0,0)\,\mathbf u_e
$$

y de ahí $\sigma_{vm}$ (`HexMesh.von_mises`). Evaluar en el centro es la opción más
estable para el H8 (los puntos de Gauss darían 8 valores por elemento).

## 3.9 Validación: viga en voladizo

La teoría de vigas de Euler-Bernoulli predice la flecha en el extremo de una viga
empotrada de longitud $L$, sección $b\times t$ y carga $P$:

$$
\delta = \frac{P L^3}{3 E I},\qquad I = \frac{b\,t^3}{12}
$$

Con $L$ = 100, $b = t$ = 20, $E$ = 1 000, $P$ = 100 → $\delta$ = 2.500 mm.
Nuestro FEM (40×8×8 elementos) da **2.515 mm** (+0.6 %, la diferencia es la
deformación por cortante que Euler-Bernoulli desprecia). El test
`tests/test_fem.py` lo verifica automáticamente.

**Ejercicio:** repite con 20×4×4, 40×8×8 y 80×16×16 elementos. Verás que la flecha
converge, pero la tensión máxima en el empotramiento sigue creciendo
(singularidad, cap. 2.7).

## 3.10 Coste y resolución

| Rejilla (pieza maciza) | GDL ≈ | Un análisis (AMG, 1 núcleo) |
|------------------------|-------|------------------------------|
| 32 × 16 × 16 | 25 k | ~0.3 s |
| 40 × 20 × 20 | 53 k | ~3 s |
| 64 × 32 × 32 | 210 k | ~3–7 s (multinúcleo) |

Una optimización SIMP son 50–100 análisis: de ahí el interés de la red neuronal.
Para ir más allá (millones de elementos) se usa multigrid geométrico en GPU o
paralelismo masivo (Aage et al., 2017, "Giga-voxel computational morphogenesis").

---
← [2. Mecánica](02-mecanica-estructural.md) · Siguiente: [4. Optimización topológica →](04-optimizacion-topologica.md)
