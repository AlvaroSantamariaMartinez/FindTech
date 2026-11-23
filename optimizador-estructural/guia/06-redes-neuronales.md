# 6. Redes neuronales para optimización estructural

Código: `toponet/nn/model.py`, `toponet/nn/features.py`, `toponet/nn/infer.py`.

## 6.1 Fundamentos en 10 minutos

### La neurona y la capa

Una neurona calcula una suma ponderada de sus entradas más un sesgo y aplica una
función no lineal: $y = \phi(\mathbf w^\top\mathbf x + b)$. Una **capa** son muchas
neuronas en paralelo: $\mathbf y = \phi(\mathbf W\mathbf x + \mathbf b)$. Una **red** encadena
capas: $f(\mathbf x) = f_L(\cdots f_2(f_1(\mathbf x)))$. Sin la no linealidad $\phi$, toda la
red colapsaría en una única transformación lineal.

Activaciones habituales: ReLU $\max(0,z)$; **SiLU** $z\,\sigma(z)$ (la que usa TopoNet,
suave y con mejor flujo de gradiente); **sigmoide** $\sigma(z) = 1/(1+e^{-z})$, que
lleva cualquier número a (0, 1) → la usamos al final para obtener densidades.

### Aprender = minimizar una pérdida

Dado un conjunto de ejemplos $(\mathbf x_i, \mathbf y_i)$, buscamos los parámetros
$\boldsymbol\theta$ (todos los $\mathbf W$, $\mathbf b$) que minimizan una **función de pérdida**:

$$
\mathcal L(\boldsymbol\theta) = \frac1N\sum_i \ell\big(f_{\boldsymbol\theta}(\mathbf x_i),\ \mathbf y_i\big)
$$

### Retropropagación y descenso por gradiente

La **retropropagación** (*backpropagation*) calcula $\nabla_{\boldsymbol\theta}\mathcal L$
aplicando la regla de la cadena desde la salida hacia la entrada; PyTorch lo hace
automáticamente (`loss.backward()`). Con el gradiente, se da un paso cuesta abajo:

$$
\boldsymbol\theta \leftarrow \boldsymbol\theta - \alpha\,\nabla_{\boldsymbol\theta}\mathcal L_{\text{lote}}
$$

donde $\alpha$ es la **tasa de aprendizaje** (*learning rate*) y el gradiente se estima
con un **lote** (*batch*) de ejemplos (descenso por gradiente estocástico).
**Adam/AdamW** adaptan el paso de cada parámetro con medias móviles del gradiente y
de su cuadrado; son el estándar (cap. 7).

> Paralelismo útil: SIMP también es un descenso por gradiente, pero sobre las
> densidades de **un** problema. La red aprende, sobre **miles** de problemas, a
> saltar directamente a la respuesta.

## 6.2 Redes convolucionales 3D

Una capa densa conectaría cada vóxel de entrada con cada vóxel de salida: con una
rejilla de 32×16×16×9 canales serían ~10¹⁰ pesos. Las **convoluciones** explotan dos
propiedades de los problemas físicos:

* **Localidad:** lo que pasa en un vóxel depende sobre todo de sus vecinos.
* **Invariancia por traslación:** la física es la misma en cualquier punto del espacio.

Una convolución 3D desliza un pequeño núcleo (3×3×3) sobre la rejilla; los mismos
27·C_in pesos se reutilizan en todas las posiciones. Apilando capas, cada vóxel de
salida "ve" una región cada vez mayor: el **campo receptivo**.

**El problema del campo receptivo:** en estructuras, una carga en un extremo afecta
a los apoyos del otro extremo. La red necesita un campo receptivo del tamaño de la
pieza. Con convoluciones 3×3×3 sin reducción haría falta una profundidad enorme.
Solución: **reducir la resolución** (*downsampling*) → U-Net.

## 6.3 La U-Net

Propuesta para segmentación médica (Ronneberger et al. 2015; versión 3D de Çiçek et
al. 2016). Es la arquitectura más usada en la literatura de optimización topológica
con redes, porque el problema es justamente una "segmentación": decidir para cada
vóxel si es material o no.

```
 entrada 9×X×Y×Z                                            salida 1×X×Y×Z
   │                                                              ▲
   ▼                                                              │ conv 1×1
 [ResBlock 16] ─────────────── salto (copia) ──────────────► [ResBlock 16]
   │ conv 2×2×2 /2                                               ▲ conv transpuesta ×2
   ▼                                                              │
 [ResBlock 32] ──────────────── salto ─────────────────► [ResBlock 32]
   │ /2                                                          ▲ ×2
   ▼                                                              │
 [ResBlock 64] ───────────── salto ──────────────► [ResBlock 64]
   │ /2                                                          ▲ ×2
   ▼                                                              │
 [ResBlock 128]  cuello de botella: visión global (X/8 × Y/8 × Z/8)
```

* **Codificador** (bajada): reduce la resolución a la mitad en cada nivel y duplica
  los canales. Al fondo, cada vóxel "ve" toda la pieza: aquí se decide la topología
  global (por dónde van las barras principales).
* **Decodificador** (subida): recupera la resolución.
* **Conexiones de salto:** copian el mapa de características del codificador al nivel
  correspondiente del decodificador. Sin ellas se perderían los detalles finos
  (bordes, la posición exacta de apoyos y cargas).

### Bloques de TopoNet

Cada `ResBlock` es:

```
x ─► Conv3d 3×3×3 ─► GroupNorm ─► SiLU ─► (Dropout) ─► Conv3d 3×3×3 ─► GroupNorm ─►(+)─► SiLU
 └───────────────────────── (conv 1×1 si cambian los canales) ──────────────────────┘
```

* **Conexión residual** (He et al. 2016): el bloque aprende una corrección $F(x)$ y
  devuelve $x + F(x)$. Facilita el flujo del gradiente y el entrenamiento de redes profundas.
* **GroupNorm** (Wu & He 2018) en lugar de BatchNorm: normaliza por grupos de canales
  dentro de cada muestra, por lo que funciona igual con lotes pequeños (en 3D la
  memoria obliga a lotes de 2–8). BatchNorm con lotes pequeños es inestable.
* **Downsampling aprendido** (conv 2×2×2 con paso 2) en lugar de *max-pooling*; y
  **convolución transpuesta** para subir.

Con `base=16, depth=3` la red tiene **1 469 841 parámetros** (la mayoría en los niveles
profundos: `enc` 883 k, `dec` 447 k). Es pequeña a propósito: entrena en CPU en
minutos y con pocos cientos de muestras no conviene una red mayor (sobreajuste).

**Tamaño de entrada:** la red es *totalmente convolucional*, así que acepta cualquier
rejilla cuyas dimensiones sean múltiplo de $2^{depth}$ = 8. `pad_to_multiple()` rellena
con ceros (= "fuera de la pieza") y luego se recorta la salida. Entrenada a 32×16×16
puede usarse a 40×21×35: generaliza razonablemente porque sus entradas son locales y
físicas, aunque con más error (ver cap. 8 para cómo se corrige).

## 6.4 ¿Qué recibe la red? Codificación del problema

Una red solo puede aprender lo que se le da como entrada. `build_features()` crea 9
canales con la resolución de la rejilla:

| Canal | Contenido | Por qué |
|-------|-----------|---------|
| 0 dominio | 1 dentro de la pieza | Dónde puede haber material |
| 1 no diseñable | 1 en zonas obligatorias | Material forzado |
| 2 apoyos | fracción de GDL bloqueados en el elemento | Dónde termina el camino de carga |
| 3–5 Fx, Fy, Fz | fuerza en el elemento / máx. | Dónde empieza y en qué dirección |
| 6 fracción de volumen | constante $V^*$ | La "consigna": cuánto material dejar |
| 7 energía (pieza maciza) | $\log_{10}(w/w_{max})/6 + 1$ | **Rasgo físico**: por dónde fluye la carga |
| 8 von Mises (pieza maciza) | $\sqrt{\sigma_{vm}/\sigma_{max}}$ | **Rasgo físico**: dónde se concentran las tensiones |

### La idea clave: rasgos físicos

Los canales 0–6 describen el problema de forma "geométrica": la red tendría que
aprender por sí sola a resolver la elasticidad, algo muy difícil con pocos datos.
Los canales 7–8 salen de **un único análisis FEM de la pieza original maciza** (con
material unitario). Le dicen a la red *qué partes trabajan*, información que de otro
modo tendría que inferir. Esta idea aparece en varios trabajos que muestran que
mejora mucho la generalización (Zhang et al. 2019; Nie et al. 2021, *TopologyGAN*).
El coste es pequeño: un FEM frente a los 50–100 de SIMP.

Detalles:

* **Escala logarítmica** para la energía: varía varios órdenes de magnitud dentro de
  la pieza; en escala lineal casi todo valdría 0.
* **Raíz cuadrada** para la tensión: comprime los picos de las singularidades.
* **Normalización por el máximo:** invariancia a la magnitud de la carga y al
  material (cap. 2.8).

### Simetrías

Si reflejas el problema en un espejo (p. ej. $x \to -x$), la solución óptima es la
misma reflejada; pero la componente $F_x$ de las fuerzas **cambia de signo**. Esto
sirve para multiplicar los datos (aumentación, cap. 7) y para *test-time
augmentation* (TTA): predecir también los problemas reflejados y promediar
(`predict_density(..., tta=True)`). `flip_features()` y `swap_yz_features()`
implementan las transformaciones correctas de los vectores.

## 6.5 La salida y la calibración del volumen

La red produce **logits** $z_e$ (números reales); $\rho_e = \sigma(z_e)$ es la densidad.
La restricción de volumen es **dura**: si pides el 30 %, quieres el 30 %, no el 33 %.
La red lo aprende aproximadamente; `calibrate_volume()` lo garantiza exactamente:

$$
\text{buscar } b \text{ tal que } \frac{1}{N}\sum_e \sigma(z_e + b) = V^* \quad\text{(bisección)}
$$

Desplazar todos los logits por el mismo $b$ conserva el **orden** de preferencia de la
red (qué vóxeles prefiere llenar) y solo ajusta la cantidad. Es el mismo truco que la
bisección en $\lambda$ del método OC (cap. 4.6).

## 6.6 Panorama de enfoques (estado del arte)

| Enfoque | Idea | Pros | Contras | Ejemplos |
|---------|------|------|---------|----------|
| **Supervisado directo** (este proyecto) | Red problema → densidad, entrenada con soluciones SIMP | Inferencia instantánea; simple | Necesita datos; sin garantías físicas | Banga et al. 2018; Yu et al. 2019 |
| **+ rasgos físicos** (este proyecto) | Añadir campos FEM de la pieza maciza a la entrada | Generaliza mucho mejor | 1 FEM por consulta | Zhang et al. 2019; Nie et al. 2021 |
| **Acelerar SIMP** (modo híbrido de este proyecto) | La red da el punto de partida; SIMP refina | Garantías físicas; menos iteraciones | No es instantáneo | Sosnovik & Oseledets 2019 |
| **Generativos** (GAN, difusión) | Modelar la *distribución* de buenos diseños | Varias soluciones; diseños nítidos | Entrenamiento complejo | TopologyGAN; TopoDiff (Mazé & Ahmed 2023) |
| **Reparametrización neuronal** | La red ES la densidad; se optimiza con FEM, sin datos | Sin dataset; resolución continua | Tan lento como SIMP (o más) | Hoyer et al. 2019; TOuNN (Chandrasekhar & Suresh 2021) |
| **Surrogados del FEM** | Red que sustituye al FEM dentro de SIMP | Acelera cada iteración | Errores que se acumulan | Operadores neuronales (FNO, Li et al. 2021) |
| **PINN** | La ecuación física en la pérdida | Sin solver | Difícil de entrenar en 3D | Raissi et al. 2019 |

Este proyecto implementa las tres primeras filas porque ofrecen el mejor equilibrio
entre lo que aprendes, lo que cuesta entrenar en un PC y la fiabilidad del resultado.
Los otros enfoques son "siguientes pasos" (cap. 10).

### Otras representaciones geométricas

* **Mallas de tetraedros / grafos** → redes de grafos (GNN): se adaptan a cualquier
  geometría sin vóxeles, pero son más lentas y complejas.
* **Funciones implícitas** (la red recibe un punto $(x,y,z)$ y devuelve la densidad):
  resolución infinita; se combina con la reparametrización neuronal.
* **Nubes de puntos:** útiles para entradas escaneadas.

## 6.7 Lo que la red NO garantiza (y cómo lo resolvemos)

Una red minimiza un error **promedio por vóxel**. Pero en estructuras, un único vóxel
puede ser crítico: si falta en mitad de una barra, la barra queda rota y la rigidez
se desploma aunque el 99.9 % de vóxeles sean correctos. Woldseth et al. (2022)
documentan este problema en muchos trabajos publicados.

Por eso, en este proyecto la salida de la red nunca se acepta sin más:

1. calibración exacta del volumen (6.5);
2. opcionalmente, refinamiento físico con SIMP (modo **híbrido**);
3. validación FEM común con comprobaciones de integridad (cap. 8);
4. métricas físicas (no solo IoU) para evaluar el modelo (cap. 7).

---
← [5. STL y voxelización](05-stl-y-voxelizacion.md) · Siguiente: [7. Sistema de entrenamiento →](07-sistema-entrenamiento.md)
