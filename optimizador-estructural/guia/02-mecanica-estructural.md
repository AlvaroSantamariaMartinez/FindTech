# 2. Mecánica estructural: lo imprescindible

Para que una red "optimice estructuras" alguien tiene que decirle qué es una buena
estructura. Ese alguien es la mecánica de sólidos. Este capítulo resume lo necesario
(elasticidad lineal) sin dar nada por supuesto.

## 2.1 Desplazamiento y deformación

Cuando cargas una pieza, cada punto $\mathbf x$ se mueve un vector
$\mathbf u(\mathbf x) = (u_x, u_y, u_z)$: el **campo de desplazamientos**. Lo que
"estresa" al material no es el movimiento en sí (una traslación rígida no daña nada)
sino cómo cambia de un punto a otro: la **deformación** (*strain*).

En pequeñas deformaciones, el tensor de deformaciones es la parte simétrica del
gradiente del desplazamiento:

$$
\varepsilon_{ij} = \frac12\left(\frac{\partial u_i}{\partial x_j} + \frac{\partial u_j}{\partial x_i}\right)
$$

* $\varepsilon_{xx}, \varepsilon_{yy}, \varepsilon_{zz}$: estiramientos (adimensionales, p. ej. 0.001 = 0.1 %).
* $\varepsilon_{xy}, \varepsilon_{yz}, \varepsilon_{zx}$: distorsiones angulares (cizalla).

**Notación de Voigt.** Como el tensor es simétrico, basta con 6 números. Se agrupan
en un vector (usando la deformación angular de ingeniería $\gamma_{ij} = 2\varepsilon_{ij}$):

$$
\boldsymbol\varepsilon = [\varepsilon_{xx},\ \varepsilon_{yy},\ \varepsilon_{zz},\ \gamma_{xy},\ \gamma_{yz},\ \gamma_{zx}]^\top
$$

Es exactamente el orden que usa `strain_displacement()` en `toponet/fem.py`.

## 2.2 Tensión

La **tensión** (*stress*) $\boldsymbol\sigma$ es la fuerza interna por unidad de
superficie (N/mm² = MPa). También es un tensor simétrico 3×3 → 6 componentes:

$$
\boldsymbol\sigma = [\sigma_{xx},\ \sigma_{yy},\ \sigma_{zz},\ \tau_{xy},\ \tau_{yz},\ \tau_{zx}]^\top
$$

Las tres primeras son tensiones normales (tracción > 0, compresión < 0), las tres
últimas tangenciales (cizalla).

## 2.3 Ley de Hooke 3D (material isótropo)

En régimen elástico lineal, la tensión es proporcional a la deformación:

$$
\boldsymbol\sigma = \mathbf D\,\boldsymbol\varepsilon,\qquad
\mathbf D = \frac{E}{(1+\nu)(1-2\nu)}
\begin{bmatrix}
1-\nu & \nu & \nu & 0 & 0 & 0\\
\nu & 1-\nu & \nu & 0 & 0 & 0\\
\nu & \nu & 1-\nu & 0 & 0 & 0\\
0&0&0&\tfrac{1-2\nu}{2}&0&0\\
0&0&0&0&\tfrac{1-2\nu}{2}&0\\
0&0&0&0&0&\tfrac{1-2\nu}{2}
\end{bmatrix}
$$

Solo hacen falta dos constantes:

* **Módulo de Young $E$** (MPa): rigidez del material. PLA ≈ 3 500, aluminio ≈ 69 000, acero ≈ 210 000.
* **Coeficiente de Poisson $\nu$**: cuánto se estrecha lateralmente al estirarse (0.3–0.4 en la mayoría).

Implementado en `constitutive_matrix()` (`toponet/fem.py`). Los materiales
predefinidos están en `toponet/problem.py` (`MATERIALS`).

> **Impresión 3D.** Las piezas impresas por FDM son **anisótropas**: son más débiles
> entre capas (eje Z) que dentro de cada capa. El modelo isótropo es una
> aproximación; en el capítulo 8 se explica cómo tenerlo en cuenta con márgenes.

## 2.4 Equilibrio

Cada trozo de material está en equilibrio: las fuerzas internas compensan las
externas. En forma diferencial:

$$
\nabla\cdot\boldsymbol\sigma + \mathbf b = \mathbf 0 \quad\text{en } \Omega
$$

con condiciones de contorno:

* **Apoyos (Dirichlet):** $\mathbf u = \mathbf 0$ en la zona sujeta $\Gamma_u$.
* **Cargas (Neumann):** $\boldsymbol\sigma\mathbf n = \mathbf t$ en la zona cargada $\Gamma_t$.

Si no hay apoyos suficientes para impedir los 6 movimientos de sólido rígido (3
traslaciones + 3 rotaciones), el problema **no tiene solución única**: la pieza
"saldría volando". Por eso la WebUI exige al menos un apoyo y por eso el
validador detecta trozos de material sin apoyo.

## 2.5 Energía de deformación y flexibilidad (compliance)

Al deformarse, el material almacena energía (como un muelle). Por unidad de volumen:

$$
w = \tfrac12\,\boldsymbol\sigma^\top\boldsymbol\varepsilon = \tfrac12\,\boldsymbol\varepsilon^\top\mathbf D\,\boldsymbol\varepsilon
$$

La energía total es $W = \int_\Omega w\,dV$. Por el teorema de Clapeyron, el trabajo
de las cargas externas es el doble de esa energía:

$$
c \;=\; \mathbf F^\top\mathbf u \;=\; 2W
$$

$c$ es la **flexibilidad** (*compliance*): cuanto **menor**, más **rígida** es la
pieza. Es el objetivo clásico de la optimización topológica porque:

1. resume la rigidez global en un número;
2. su derivada respecto a la densidad de cada elemento es baratísima (cap. 4);
3. minimizarla tiende a producir estructuras que llevan la carga por el camino más
   directo hasta los apoyos → buena integridad.

**Intuición clave:** la energía de deformación de cada elemento indica *cuánto
trabaja* ese elemento. Los elementos con poca energía "no hacen nada" y se pueden
quitar; los de mucha energía están en el camino de la carga. Esta idea está detrás
de SIMP, de BESO y de los **rasgos físicos** que le damos a la red (cap. 6).

## 2.6 Rigidez ≠ resistencia

* **Rigidez:** cuánto se deforma (depende de $E$ y de la geometría).
* **Resistencia:** cuánta tensión aguanta antes de fallar (depende del material: $\sigma_y$).

Una pieza puede ser muy rígida y aun así tener un punto con tensión excesiva (una
esquina viva, una barra muy fina). Minimizar la flexibilidad **no** garantiza
resistencia, por eso la validación (cap. 8) comprueba ambas cosas por separado.

## 2.7 Criterio de von Mises y factor de seguridad

¿Cómo comparar un estado de tensión de 6 componentes con un único número del
ensayo de tracción ($\sigma_y$)? Para materiales dúctiles (metales, la mayoría de
plásticos) se usa la **tensión equivalente de von Mises**:

$$
\sigma_{vm} = \sqrt{\tfrac12\left[(\sigma_{xx}-\sigma_{yy})^2 + (\sigma_{yy}-\sigma_{zz})^2 + (\sigma_{zz}-\sigma_{xx})^2\right] + 3\left(\tau_{xy}^2+\tau_{yz}^2+\tau_{zx}^2\right)}
$$

El material empieza a plastificar cuando $\sigma_{vm} \geq \sigma_y$. El **factor de
seguridad** es el margen:

$$
FS = \frac{\sigma_y}{\max \sigma_{vm}}
$$

* $FS = 1$: justo en el límite. $FS = 2$: aguantaría el doble de carga (en régimen lineal).
* Valores típicos de diseño: 1.5–2 (metales, cargas conocidas), 2–4 (plásticos
  impresos, cargas inciertas, fatiga).

Implementado en `HexMesh.von_mises()` y usado en `toponet/analysis.py`.

### Singularidades de tensión (¡importante!)

En una esquina entrante perfecta, o justo donde aplicas una fuerza en un punto, la
tensión teórica es **infinita**. En un modelo de vóxeles, cada escalón de la
superficie es una esquina entrante. Consecuencia: el **máximo** de $\sigma_{vm}$
crece al refinar la malla y no es fiable. Por eso este proyecto calcula el factor
de seguridad con el **percentil 99** de la tensión (ignora el 1 % de elementos más
cargados, típicamente esos picos numéricos) y muestra el máximo como referencia.
Para un diseño definitivo, re-analiza la pieza suavizada con un FEM de calidad
(malla de tetraedros cuadráticos refinada en las zonas críticas).

## 2.8 Linealidad e invariancia de escala

En elasticidad lineal:

* si multiplicas todas las cargas por $k$, desplazamientos y tensiones se multiplican por $k$;
* si multiplicas $E$ por $k$, los desplazamientos se dividen por $k$ (las tensiones no cambian);
* **la topología óptima de mínima flexibilidad no cambia** con ninguno de esos factores.

Esto tiene una consecuencia práctica enorme para la red neuronal: podemos entrenarla
con cargas de magnitud 1 y $E=1$ y usarla con cualquier material y magnitud de carga.
Solo importan la **geometría**, la **dirección relativa** de las cargas, los
**apoyos** y la **fracción de volumen** (ver `toponet/nn/features.py`, que normaliza
todo). Después, las métricas absolutas (MPa, mm, FS) se calculan con los valores
reales en la validación.

## 2.9 Qué NO cubre este modelo (y conviene saber)

> El **análisis avanzado** del [capítulo 11](11-fisica-realista.md) cubre el pandeo, la
> fatiga, la anisotropía de la impresión 3D, el peso propio y las frecuencias naturales
> sobre la geometría real. La tabla siguiente describe el modelo rápido de vóxeles que
> usa el optimizador.


| Fenómeno | Por qué importa | Qué hacer |
|----------|-----------------|-----------|
| **Pandeo** | Barras esbeltas en compresión fallan muy por debajo de $\sigma_y$ | Evitar barras muy finas comprimidas; análisis de pandeo lineal |
| **Fatiga** | Cargas repetidas rompen a tensiones bajas | Usar FS más altos (≥ 3) y radios generosos |
| **No linealidad** | Grandes deformaciones, contacto, plasticidad | FEM no lineal |
| **Anisotropía** | Impresión 3D, compuestos | Orientar la pieza, reducir $\sigma_y$ efectivo entre capas |
| **Cargas dinámicas** | Impactos, vibraciones | Análisis modal/transitorio |

---
← [1. Visión general](01-vision-general.md) · Siguiente: [3. Elementos finitos →](03-elementos-finitos.md)
