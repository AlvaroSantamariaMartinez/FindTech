# 4. Optimización topológica: el modelo de base (SIMP)

Este capítulo explica el optimizador clásico incluido en la aplicación
(`toponet/simp.py`, plugin "SIMP clásico (base)"). Es importante por tres motivos:

1. es la **referencia** contra la que comparar tu red;
2. genera las **etiquetas** con las que se entrena la red;
3. se usa como **refinamiento físico** en el modo híbrido.

## 4.1 Formulación

Asignamos a cada elemento $e$ una variable de diseño $x_e\in[0,1]$ y planteamos:

$$
\begin{aligned}
\min_{\mathbf x}\quad & c(\mathbf x) = \mathbf F^\top\mathbf u(\mathbf x) \\
\text{s.a.}\quad & \mathbf K(\mathbf x)\,\mathbf u = \mathbf F \\
& \frac{1}{N}\sum_e \bar x_e = V^* \\
& 0 \le x_e \le 1
\end{aligned}
$$

"La estructura más rígida posible que usa exactamente una fracción $V^*$ del volumen".

El problema real es **discreto** (cada vóxel está lleno o vacío): con $N$ elementos
habría $2^N$ combinaciones; con $N=10\,000$, más que átomos en el universo. La clave
de los métodos de densidad es **relajarlo a continuo** y empujar luego la solución
hacia 0/1.

## 4.2 SIMP: interpolación con penalización

**SIMP** (*Solid Isotropic Material with Penalization*) define el módulo de cada elemento:

$$
E_e(\bar x_e) = E_{min} + \bar x_e^{\,p}\,(E_0 - E_{min})
$$

* $E_{min}$ ≈ $10^{-6}E_0$ evita que $\mathbf K$ sea singular donde no hay material.
* $p$ = 3 es el valor clásico.

**¿Por qué $p>1$?** Con $p=1$ un elemento a densidad 0.5 aporta la mitad de rigidez
por la mitad de material: el óptimo estaría lleno de "material gris" (densidades
intermedias), que no se puede fabricar. Con $p=3$, ese elemento aporta solo
$0.5^3 = 12.5\,\%$ de la rigidez pero "cuesta" el 50 % del volumen. Sale a cuenta
decidir: 0 o 1.

## 4.3 Análisis de sensibilidad (el gradiente)

Para optimizar necesitamos $\partial c/\partial x_e$ para **todos** los elementos.
Hacerlo por diferencias finitas costaría un FEM por elemento: inviable. El
**método adjunto** lo da casi gratis.

Derivamos $c = \mathbf F^\top\mathbf u$ (las cargas no dependen del diseño):

$$
\frac{\partial c}{\partial x_e} = \mathbf F^\top \frac{\partial\mathbf u}{\partial x_e}
$$

Derivando el equilibrio $\mathbf K\mathbf u = \mathbf F$:
$\frac{\partial\mathbf K}{\partial x_e}\mathbf u + \mathbf K\frac{\partial\mathbf u}{\partial x_e} = 0
\Rightarrow \frac{\partial\mathbf u}{\partial x_e} = -\mathbf K^{-1}\frac{\partial\mathbf K}{\partial x_e}\mathbf u$.

Sustituyendo y usando que $\mathbf K$ es simétrica ($\mathbf F^\top\mathbf K^{-1} = \mathbf u^\top$):

$$
\boxed{\frac{\partial c}{\partial x_e} = -\mathbf u^\top\frac{\partial\mathbf K}{\partial x_e}\mathbf u
= -p\,\bar x_e^{\,p-1}(E_0-E_{min})\,h\;\mathbf u_e^\top\mathbf K_e^0\,\mathbf u_e}
$$

Observa:

* Es **siempre ≤ 0**: añadir material nunca hace la estructura más flexible.
* Es proporcional a la **energía de deformación del elemento**: los elementos que
  más trabajan son los que más interesa reforzar (la intuición del cap. 2.5).
* Solo necesita el desplazamiento $\mathbf u$ que ya hemos calculado: **un FEM por
  iteración da el gradiente completo**. (La flexibilidad es "auto-adjunta".)

En el código: `res.ce` = $\mathbf u_e^\top\mathbf K_e^0\mathbf u_e$ por elemento, y
`dc_b = -penal * ... * res.ce`.

## 4.4 Filtros: tableros de ajedrez y dependencia de malla

Sin regularización, SIMP produce dos patologías:

1. **Tableros de ajedrez:** patrones 0/1 alternos que el H8 sobrevalora numéricamente.
2. **Dependencia de malla:** al refinar la malla aparecen barras cada vez más finas
   (el problema continuo no tiene solución sin controlar la escala).

**Filtro de densidad** (Bruns & Tortorelli 2001; Bourdin 2001): la densidad "física"
es una media ponderada de las vecinas dentro de un radio $r_{min}$:

$$
\tilde x_e = \frac{\sum_{i\in N_e} H_{ei}\,x_i}{\sum_{i\in N_e}H_{ei}},\qquad H_{ei} = \max\left(0,\; r_{min} - \|\mathbf c_e - \mathbf c_i\|\right)
$$

Esto impone un **tamaño mínimo de miembro** ≈ $2r_{min}$ y elimina los tableros.

Implementación (`DensityFilter`): como la rejilla es regular, la suma ponderada es
una **convolución 3D** con un núcleo cónico (`scipy.ndimage.convolve`). Los
vóxeles de fuera del dominio se excluyen multiplicando por la máscara antes de
convolucionar y normalizando con $H_s = H * \text{máscara}$.

**Regla de la cadena:** las sensibilidades se calculan respecto a $\tilde x$ y hay que
llevarlas a $x$: $\frac{\partial c}{\partial x_i} = \sum_e \frac{\partial c}{\partial\tilde x_e}\frac{H_{ei}}{H_{s,e}}$,
que es otra convolución (`DensityFilter.backward`).

## 4.5 Proyección de Heaviside: diseños nítidos

El filtro deja una franja gris en los bordes. Una **proyección** suave tipo escalón
la elimina (Wang, Lazarov & Sigmund 2011):

$$
\bar x_e = \frac{\tanh(\beta\eta) + \tanh(\beta(\tilde x_e-\eta))}{\tanh(\beta\eta) + \tanh(\beta(1-\eta))}
$$

con umbral $\eta = 0.5$. Con $\beta\to 0$ no hace nada; con $\beta$ grande es un
escalón. Se usa **continuación**: $\beta$ = 1 → 2 → 4 → 8, duplicándolo cuando el
diseño se estabiliza (o cada 20 iteraciones). Empezar directamente con $\beta$ alto
atrapa la optimización en malos mínimos locales.

Con la proyección, un cambio pequeño en $x$ mueve mucho $\bar x$; por eso el código
reduce el paso máximo (`move / sqrt(beta)`). Sin esa corrección observamos
oscilaciones con el cambio clavado en el límite (0.2) durante decenas de iteraciones.

## 4.6 Actualización: Criterios de Optimalidad (OC)

Condición de óptimo (Lagrangiano con multiplicador $\lambda$ para el volumen):
$\frac{\partial c}{\partial x_e} + \lambda\frac{\partial V}{\partial x_e} = 0$. Definiendo

$$
B_e = \frac{-\partial c/\partial x_e}{\lambda\,\partial V/\partial x_e}
$$

en el óptimo $B_e = 1$ para los elementos intermedios. El esquema OC es un punto fijo:

$$
x_e^{nuevo} = \operatorname{clip}\!\left(x_e\,\sqrt{B_e},\ \ x_e - m,\ \ x_e + m\right)\cap[0,1]
$$

* $m$ = límite de movimiento (0.2): estabilidad.
* $\lambda$ se busca por **bisección** para que el nuevo diseño cumpla exactamente el
  volumen objetivo (el volumen se mide sobre $\bar x$, tras filtro y proyección).

Interpretación: si un elemento trabaja más que la media ($B_e > 1$) gana material;
si trabaja menos, lo pierde. OC es sencillo y muy eficaz para un único objetivo con
una única restricción de volumen. Para problemas con varias restricciones (tensión,
desplazamiento, frecuencias) se usa **MMA** (*Method of Moving Asymptotes*, Svanberg 1987).

## 4.7 Bucle completo

```
x = V*  (uniforme)                     ← run_simp()
repetir:
    x̃ = filtro(x);  x̄ = proyección(x̃)   ← physical()
    K(x̄) u = F                          ← HexMesh.solve()  (1 FEM)
    c = Fᵀu ;  dc/dx̄ = -p x̄^(p-1) ... uₑᵀKₑuₑ
    dc/dx = filtroᵀ(dc/dx̄ · dx̄/dx̃)      ← regla de la cadena
    x = OC(x, dc/dx, dV/dx)  con bisección en λ
    si converge: β ← 2β
hasta cambio < 1 % con β máximo, o max_iter
```

## 4.8 Zonas no diseñables

Los elementos marcados como **no diseñables** (`passive_solid`) se fijan a densidad 1
y no se optimizan. Se usan alrededor de apoyos y cargas (opción "zona no diseñable"
en la WebUI) para que el optimizador no deje un tornillo "flotando en el aire" o
quite material justo donde se aplica la fuerza. La fracción de volumen se define
sobre el volumen total de la pieza, contando estas zonas.

## 4.9 Ejemplo resuelto

Voladizo 48×16×4, empotrado en x = 0 y cargado en la arista inferior del extremo,
$V^*$ = 30 %. Sección intermedia del resultado (█ = material):

```
███████████████████████████████████▒
████████████████████████████████████▒
   ▒████▒                   ▒████████▒
     ▒███▒                  ▒█████▒███▒
       ▒████▒            ▒█████▒    ▒███▒
          ▒█████▒       ▒████▒        ▒███▒
           ▒█████      ▒████▒          ▒███▒
        ▒▒██▒▒▒███▒  ▒████▒              ▒███▒
      ▒███▒    ▒████████▒                  ▒███▒
██████████████████████▒                     ▒███
████████████████████████████████████████████████
```

Aparecen los cordones superior e inferior (flexión) y diagonales (cortante): una
celosía, como las que diseñaría un ingeniero. En las capas interiores el material es
más escaso: en 3D el material migra a las caras exteriores (como en una viga en I).

## 4.10 Alternativa incluida: BESO (plugin de ejemplo)

`plugins/eso_ejemplo.py` implementa **BESO** (*Bi-directional Evolutionary Structural
Optimization*, Huang & Xie 2007). En lugar de densidades continuas:

1. Calcula la "sensibilidad" (energía de deformación, filtrada) de cada elemento.
2. Reduce el volumen objetivo un pequeño porcentaje (tasa de evolución, p. ej. 4 %).
3. Mantiene sólidos los elementos de mayor sensibilidad y "mata" el resto (densidad
   $10^{-3}$, *soft-kill*); los muertos pueden revivir si su sensibilidad sube.
4. Repite hasta alcanzar el volumen y estabilizarse.

Necesita aproximadamente $\log(V^*)/\log(1-\text{tasa})$ iteraciones para alcanzar el
volumen (≈ 30 para $V^*$ = 30 % y 4 %). Es más heurístico que SIMP pero produce
directamente diseños 0/1. Sirve en la app para comparar un tercer método y, sobre
todo, como **plantilla** para tus propios plugins (cap. 9).

## 4.11 Limitaciones y extensiones

* **Óptimos locales:** el problema no es convexo; distintos parámetros ($r_{min}$, $p$,
  $\beta$) dan diseños distintos e igual de buenos. Para la red esto es "ruido en las
  etiquetas" (cap. 7).
* **Restricciones de tensión:** minimizar flexibilidad no limita la tensión máxima.
  Se puede añadir una restricción agregada $\left(\sum_e \sigma_{vm,e}^P\right)^{1/P}\le\sigma_{lim}$
  (norma-P, Le et al. 2010) con MMA. Es el siguiente paso natural (cap. 10).
* **Fabricación:** voladizos para impresión 3D, simetrías, extrusión, espesor mínimo
  y máximo... se añaden con filtros y restricciones adicionales.
* **Múltiples casos de carga:** minimizar $\sum_k w_k c_k$ (un FEM por caso).

---
← [3. Elementos finitos](03-elementos-finitos.md) · Siguiente: [5. STL y voxelización →](05-stl-y-voxelizacion.md)
