# 11. Física realista: el análisis avanzado

Código: `toponet/physics/` (`advanced.py`, `tetmesh.py`), tests en `tests/test_physics.py`.

Los capítulos 2–4 usan un modelo deliberadamente sencillo (vóxeles, elasticidad
lineal, un caso de carga) porque el optimizador necesita repetir el análisis cientos
de veces. Ese modelo sirve para **decidir dónde poner material**, pero no para
**afirmar que la pieza aguanta**. Para eso está el *análisis avanzado*: se aplica a la
pieza original o a cualquier diseño y modela la física que de verdad decide si una
pieza falla.

## 11.1 Por qué hacía falta: dos problemas que destapó

Al validar los diseños con física realista aparecieron dos errores del enfoque
"solo vóxeles":

1. **El STL exportado perdía material.** El marching cubes a nivel 0.5 sobre
   densidades por elemento adelgaza las barras finas: una barra de un vóxel queda con
   sección de rombo (la mitad del área) y el suavizado la estrecha más. En un caso de
   prueba con barras finas, el STL tenía **el 12 %** del volumen del diseño; en el
   soporte en L optimizado, un 40 % menos de masa (11 g frente a 19 g) y un
   desplazamiento **9 veces mayor** que el validado. Corrección: `solid_to_mesh()`
   malla exactamente los vóxeles validados (sin islas), suavizados con un filtro
   gaussiano, y elige por bisección el nivel que **conserva su volumen** (error < 0.3 %).
2. **La resistencia por vóxeles es optimista.** El factor de seguridad con el
   percentil 99 de la tensión por vóxeles daba 2.2 en el diseño SIMP del soporte; el
   análisis con tetraedros cuadráticos sobre la geometría suave da 1.4. En la pieza
   original con esquina viva: 4.2 frente a 1.7. Por eso la tabla rápida ahora lo
   advierte y la decisión final debe tomarse con el análisis avanzado.

## 11.2 Qué física y de dónde sale

La física no está escrita desde cero: procede de proyectos establecidos y
revisados por la comunidad. Este proyecto solo los conecta y valida.

| Física | Fuente | Licencia |
|--------|--------|----------|
| Elasticidad lineal 3D (elementos P2) y matriz del hexaedro del optimizador | [scikit-fem](https://github.com/kinnala/scikit-fem) (`skfem.models.elasticity`) | BSD-3 |
| Malla de tetraedros de la geometría real | [fTetWild](https://github.com/wildmeshing/fTetWild) vía [pytetwild](https://github.com/pyvista/pytetwild) | MPL-2.0 |
| Malla de respaldo | [gmsh](https://gmsh.info) | GPL-2.0+ |
| Pandeo lineal (rigidez geométrica) | J. Bleyer, *Numerical Tours of Computational Mechanics* ([comet-fenicsx](https://github.com/bleyerj/comet-fenicsx)), tour "Linear buckling analysis of a 3D solid" | CC BY-SA 4.0 |
| Frecuencias naturales | scikit-fem, ejemplo `ex03.py` | BSD-3 |
| Fatiga: curva S-N y corrección de Goodman | [fatpack](https://github.com/Gunnstein/fatpack) | ISC |
| Material transversalmente isótropo | Bleyer, tour "Isotropic and orthotropic plane stress elasticity" (extendido a 3D) | CC BY-SA 4.0 |
| Delaminación entre capas | criterio de Brewer & Lagace (1988) | — |

Incluso el FEM rápido de vóxeles del optimizador toma ahora la matriz del elemento de
scikit-fem; un test comprueba que la matriz global coincide con la que ensambla
scikit-fem con un error de 10⁻¹⁶.

## 11.3 Malla de tetraedros de la geometría real

Para analizar la forma real (superficies suaves, taladros redondos) hace falta una
malla de volumen ajustada a ella. Se usa **fTetWild** (Hu et al., 2020), diseñado para
superficies "salvajes": acepta auto-intersecciones, agujeros pequeños y triángulos
degenerados, y siempre termina. Para conseguirlo construye la malla dentro de una
*envolvente*: la superficie resultante está a menos de 10⁻³ × diagonal de la original
(el volumen cambia menos de un 0.1 %).

gmsh queda como respaldo. Con gmsh, la reparametrización del STL (tutorial t13) o la
recuperación del contorno pueden **no terminar nunca** con superficies imperfectas
(nos ocurrió con el soporte en L), algo inaceptable en un programa interactivo.

Calidades de malla (elementos a lo largo de la pieza / nodos máximos):
`rápida` 12 / 2 500 · `normal` 16 / 4 000 · `fina` 24 / 9 000.

## 11.4 Elementos cuadráticos (P2)

El tetraedro lineal (P1) tiene deformación constante: en flexión sufre *bloqueo*
(*locking*) y resulta muchísimo más rígido de lo real. El tetraedro **cuadrático** P2
(10 nodos) representa la flexión con pocos elementos: con un solo elemento en el
canto, la columna de Euler da el pandeo con un 0.1 % de error.

Con desplazamientos cuadráticos la tensión es **lineal** dentro de cada tetraedro, así
que su máximo está en un vértice. Por eso las tensiones se evalúan en los vértices de
cada elemento (en los puntos de Gauss, interiores, se subestiman: en la viga de
validación, 12.6 MPa en lugar de 14).

## 11.5 Zonas de aplicación de cargas: principio de Saint-Venant

Un apoyo o una carga "ideal" (desplazamiento nulo o fuerza repartida sobre unas pocas
caras) crea tensiones singulares en su borde: crecen sin límite al refinar la malla.
En la realidad, un tornillo con arandela o una superficie de contacto reparten la
carga. El principio de Saint-Venant dice que, a una distancia del orden del tamaño de
la zona cargada, la tensión ya no depende de cómo se aplique la carga.

Por eso se informan **dos** factores de seguridad:

* **FS de diseño**: fuera de las zonas de aplicación (radio 1.5 × tamaño de elemento).
  Es el representativo del diseño.
* **FS incluyendo las zonas de apoyo y carga**: si es muy bajo, revisa el detalle de
  la unión (arandelas más grandes, más tornillos, radios).

En la viga de validación, la tensión de diseño coincide con la teoría de vigas en ese
punto con un error del 1 %, mientras que en el propio empotramiento sale un 10 % más
alta: es exactamente la singularidad del empotramiento ideal.

> **Esquinas vivas.** Una esquina interior perfectamente viva (como la del soporte en
> L de ejemplo) también es una singularidad, pero geométrica: es real. En CAD, añade
> siempre un redondeo; si no, la tensión máxima dependerá de la malla.

## 11.6 Peso propio

Fuerza de volumen $\rho\,\mathbf g$ en dirección −Z. Con el sistema de unidades
mm-N-s, la masa va en **toneladas**: $\rho$ [t/mm³] = $\rho$ [g/cm³] × 10⁻⁹ y
$g$ = 9 810 mm/s². Su efecto es despreciable en piezas pequeñas de plástico (0.7 N en
el soporte de ejemplo, frente a 200 N de carga) y decisivo en piezas grandes o pesadas.

Comprobación de equilibrio: la suma de las reacciones en los apoyos iguala a las cargas
aplicadas más el peso (error relativo ~10⁻¹², se informa en cada análisis).

## 11.7 Pandeo lineal

Una pieza esbelta comprimida puede fallar de golpe, muy por debajo de su resistencia:
pandea. Siguiendo el tour de Bleyer, se parte de la energía potencial con la
deformación de Green-Lagrange y se busca dónde la segunda variación deja de ser
definida positiva. Linealizando en torno al estado precargado $\boldsymbol\sigma_0$
(producido por las cargas de diseño):

$$
\mathbf K\,\boldsymbol\phi = \lambda\,\mathbf K_G(\boldsymbol\sigma_0)\,\boldsymbol\phi,\qquad
\mathbf K_G(\delta\mathbf u,\mathbf v) = -\int_\Omega \boldsymbol\sigma_0 : \left(\nabla\delta\mathbf u^\top\nabla\mathbf v\right)\,d\Omega
$$

$\lambda$ es el **factor de carga de pandeo**: las cargas pueden multiplicarse por
$\lambda$ antes de que la pieza pandee. Se resuelve el problema inverso
$\mathbf K_G\boldsymbol\phi = \mu\mathbf K\boldsymbol\phi$ con $\mu = 1/\lambda$, que solo
necesita factorizar (o precondicionar) $\mathbf K$, que es definida positiva.

**Objetivo $\lambda \geq 3$.** El pandeo real ocurre antes que el lineal por las
imperfecciones (geometría, excentricidad de cargas, tensiones residuales de la
impresión). Factores de 2–4 son habituales en diseño.

### Modos locales espurios (estudio de convergencia)

Con la carga del soporte en L aplicada sobre un pequeño parche, $\lambda$ no convergía
al refinar la malla: 96.6 → 61.5. El modo era un "pandeo" local justo bajo la carga
idealizada, un artefacto de la carga puntual. Anulando la pretensión en las zonas de
aplicación de cargas y apoyos *concentrados* (las mismas de 11.5):

| Malla | GDL | λ sin exclusión | λ con exclusión 1.5·h | con 3·h |
|-------|-----|-----------------|-----------------------|---------|
| 10 elementos | 41 k | 96.6 | 124.4 | 124.4 |
| 14 elementos | 70 k | 61.5 | 120.8 | 120.8 |

El valor con exclusión no depende del radio de exclusión y converge con la malla. Con
cargas o apoyos de **cara completa** (tracción uniforme) no hay singularidad y no se
excluye nada: la columna de Euler da el valor teórico.

Validaciones: columna empotrada-libre $P_{cr} = \pi^2 EI/4L^2$ → error < 3 % (0.1 % con
malla fina); voladizo de sección cuadrada con carga en la punta: $\lambda$ = 10.70 frente
a 10.77 de la fórmula de Timoshenko para el pandeo lateral-torsional.

## 11.8 Frecuencias naturales

Como en el ejemplo ex03 de scikit-fem: $\mathbf K\boldsymbol\phi = \omega^2\mathbf M\boldsymbol\phi$,
con la matriz de masa $\mathbf M = \int\rho\,\mathbf u\cdot\mathbf v$. Si la pieza va a
estar sometida a vibraciones (motores, ventiladores, vehículos), su primera frecuencia
debe estar bien por encima de la de excitación (regla habitual: más del doble).
Validación: voladizo, $f_1 = \frac{1.875^2}{2\pi}\sqrt{EI/\rho A L^4}$ → error −0.2 %.

Al aligerar una pieza su frecuencia suele **subir** (pierde más masa que rigidez): en el
soporte de ejemplo pasa de ~480 Hz a ~950 Hz.

## 11.9 Fatiga

Una carga que se repite rompe la pieza a tensiones muy inferiores a su resistencia.
Se evalúa en el punto más solicitado (fuera de las zonas de aplicación):

1. La carga oscila entre $R\,\sigma_{max}$ y $\sigma_{max}$ (R = 0: de cero al máximo;
   R = −1: alterna). Rango $\Delta\sigma = (1-R)\sigma_{max}$, media
   $\sigma_m = (1+R)\sigma_{max}/2$.
2. **Goodman** (`fatpack.find_goodman_equivalent_stress`): la tensión media de tracción
   reduce la vida; se convierte a un rango equivalente con media nula
   $\Delta\sigma_{eq} = \Delta\sigma / (1 - \sigma_m/S_u)$.
3. **Basquin** (`fatpack.LinearEnduranceCurve`): $S^m N = \text{cte}$, anclada en la
   resistencia a fatiga del material (amplitud $S_f$ a $N_{ref}$ ciclos con R = −1).
4. FS a fatiga = rango admisible a los ciclos pedidos / rango equivalente; también se
   da la vida estimada.

Limitaciones: los datos S-N de plásticos impresos son escasos y muy dependientes de la
impresión; el acabado superficial, las entallas y el tamaño (factores de Marin) reducen
la resistencia a fatiga; la temperatura y la humedad también. Usa datos de ensayo
siempre que puedas (campos editables en *Propiedades para la física avanzada*).

## 11.10 Impresión 3D por capas

Una pieza FDM es más débil y algo más flexible **entre capas**. Se modela:

* **Rigidez transversalmente isótropa** (eje = dirección de apilado). Como en el tour
  ortótropo de Bleyer, se escribe la matriz de flexibilidad con los módulos de
  ingeniería y se invierte numéricamente: $E_p = E$, $\nu_p = \nu$ en el plano de capa;
  $E_z = r\,E$ perpendicular (r = 0.85 en PLA, editable); se supone $\nu_{pz} = \nu$ y
  $G_z = E_z / 2(1+\nu)$.
* **Delaminación** (Brewer & Lagace 1988): con la tensión normal a las capas
  $\sigma_{nn}$ y la cortante entre capas $\tau$,
  $\left(\langle\sigma_{nn}\rangle_+/S_n\right)^2 + (\tau/S_s)^2 \le 1$, con
  $S_n$ = adhesión entre capas × $S_u$ y $S_s = S_n$ (supuesto conservador).

La dirección de impresión importa muchísimo: prueba a cambiar el eje de capas en la
WebUI y orienta la pieza para que las tensiones principales queden dentro de las capas.

## 11.11 Solvers

* **Problemas pequeños (≤ 30 000 GDL):** factorización LU (SuperLU) y Lanczos (ARPACK)
  para los autovalores.
* **Problemas grandes:** gradiente conjugado con multigrid algebraico (pyamg, con los
  6 modos rígidos) para la estática, y **LOBPCG** (Knyazev 2001) precondicionado con un
  ciclo V del multigrid para pandeo y modos. La LU de SuperLU tardaba 150 s con 68 000
  GDL (escala mal en 3D); con LOBPCG el pandeo sale en ~25 s.

Tiempos típicos del análisis avanzado completo (soporte en L, CPU de 4 núcleos):
rápida ~50 s · normal ~60 s · fina ~80 s.

## 11.12 Resumen de validaciones (`tests/test_physics.py`)

| Prueba | Referencia | Resultado |
|--------|-----------|-----------|
| Matriz del hexaedro del optimizador | scikit-fem | error 5·10⁻¹⁷ |
| Flecha de un voladizo (P2) | Euler-Bernoulli | +0.2 % |
| Tensión de flexión a 1.5·h del empotramiento | teoría de vigas | +1 % |
| Equilibrio con peso propio | suma de reacciones | 10⁻¹² |
| Pandeo de columna empotrada-libre | Euler | < 3 % |
| Pandeo lateral-torsional | Timoshenko | −0.6 % |
| Columna en tracción | no pandea | λ = ∞ |
| 1.ª frecuencia del voladizo | analítica | −0.2 % |
| Material transversalmente isótropo | módulos de entrada | exacto |
| Fatiga a la amplitud de referencia | FS = 1, Basquin 10×N | exacto |

## 11.13 Lo que sigue sin cubrirse

* **Plasticidad**: el análisis es elástico; un FS < 1 significa "plastifica", no la
  carga de rotura.
* **Grandes deformaciones** (TPU, piezas muy flexibles): scikit-fem tiene ejemplos de
  hiperelasticidad (`ex43`, `ex55`) que serían el punto de partida.
* **Contacto** entre piezas, holguras de los tornillos.
* **Fluencia (creep)**: los plásticos se deforman con el tiempo bajo carga constante;
  el PLA además pierde rigidez por encima de ~50 °C.
* **Impactos** y cargas dinámicas no armónicas.
* **Varios casos de carga** simultáneos o alternativos.

Para piezas cuyo fallo tenga consecuencias, sigue siendo imprescindible un cálculo
profesional y ensayos.

## 11.14 Uso en la aplicación

1. Optimiza como siempre (la optimización usa el modelo rápido de vóxeles).
2. En **7. Física avanzada** elige: peso propio, impresión por capas y su eje, ciclos de
   carga y R para la fatiga, pandeo, nº de frecuencias, calidad de malla.
3. Pulsa **Análisis avanzado** en un visor, o **Analizar todos los diseños**.
4. Compara en la tabla *Análisis avanzado* y elige el color *von Mises · análisis
   avanzado* para ver las tensiones sobre la geometría real.
5. Si el diseño no pasa: más material (fracción de volumen), otro material, otra
   orientación de impresión, cargas mejor repartidas, o un umbral menor.

---
← [10. Referencias y siguientes pasos](10-referencias-y-siguientes-pasos.md) · [Índice](README.md)
