# 7. El sistema de entrenamiento

Este capítulo construye todo lo necesario para entrenar (y re-entrenar, y mejorar)
tu red: datos, aumentación, pérdidas, optimizador, métricas, diagnóstico y
experimentación.

```
 generate_data.py          dataset.py               train.py                 evaluate.py
 ┌──────────────┐   .npz   ┌──────────────┐  lotes  ┌──────────────┐  .pt   ┌──────────────┐
 │problema      │ ───────► │TopologyData- │ ──────► │U-Net + pérdi-│ ─────► │FEM: gap de   │
 │aleatorio→SIMP│          │set + aument. │         │das + AdamW   │        │flexibilidad  │
 └──────────────┘          └──────────────┘         └──────────────┘        └──────────────┘
```

## 7.1 Generar los datos

En aprendizaje supervisado la calidad del modelo depende sobre todo de los datos.
No existen datasets públicos de "piezas 3D + cargas + óptimo" adaptados a nuestro
formato, así que **los generamos** con el propio SIMP: cada muestra es un problema
aleatorio y su solución.

### 7.1.1 Problemas aleatorios (`random_problem`)

La distribución de entrenamiento debe parecerse a los problemas que verás en uso.
`random_domain()` genera, dentro de una rejilla de 32×16×16:

| Tipo | Descripción |
|------|-------------|
| `box` | sub-caja aleatoria (60–100 % de cada dimensión) |
| `L` | caja con una esquina recortada (escuadras) |
| `holes` | caja con 1–3 taladros cilíndricos en ejes aleatorios |
| `slot` | caja con una ranura |
| `plate` | placa delgada (3–6 vóxeles) |

Se conserva solo la mayor componente conexa. Después se eligen:

* **Apoyos** (uno de estos modos): una cara completa (voladizo), dos apoyos en los
  extremos (puente, a veces uno deslizante) o 2–3 parches en la superficie (tornillos).
* **Cargas:** 1–2 parches en la superficie **lejos de los apoyos** (> 35 % de la
  diagonal; si no, el problema es trivial), con dirección alineada a un eje (50 %) o
  aleatoria, y magnitud relativa 0.5–1.
* **Fracción de volumen** $V^* \sim U(0.12, 0.45)$.
* Zonas no diseñables alrededor de apoyos y cargas (como en la WebUI).

Diseñar esta distribución es **la decisión más importante** del sistema: la red solo
sabrá resolver problemas parecidos a estos. ¿Tus piezas son siempre bridas con 4
tornillos? Añade ese tipo de problema al generador.

### 7.1.2 Etiquetas: SIMP

Cada problema se resuelve con `run_simp(max_iter=50, projection=True)`; la densidad
final (casi 0/1 gracias a la proyección) es la etiqueta. Junto a ella se guardan los
rasgos de entrada, los apoyos/cargas exactos (para poder re-evaluar con FEM) y la
flexibilidad alcanzada.

### 7.1.3 Coste y paralelismo

```bash
python -m toponet.nn.generate_data --n 800 --out data/dataset --workers 4
```

* ~6–20 s por muestra en un núcleo → 640 muestras ≈ 40 min con 4 núcleos.
* Cada proceso usa **un hilo de BLAS** (`OMP_NUM_THREADS=1`): se paraleliza entre
  muestras, que es mucho más eficiente que paralelizar dentro de cada FEM pequeño.
* Cada muestra es un `.npz` independiente: si interrumpes, vuelve a lanzarlo y se
  saltan las existentes. Para **ampliar** el dataset usa otra semilla inicial
  (`--seed0 1000`).

¿Cuántos datos? Con 9 canales físicos, unos cientos de muestras ya dan una red útil
(el modelo incluido usa 640). La literatura 2D usa 10⁴–10⁵. Regla práctica: duplica
los datos mientras la pérdida de validación siga bajando de forma apreciable (7.7).

### 7.1.4 Partición train / validación / test

`split_files()` separa aleatoriamente (con semilla fija) un 10 % para validación.
Como cada archivo es un problema distinto, no hay fuga de información. Si generas
variantes de un mismo problema (p. ej. distintos $V^*$), sepáralas **por problema**,
no por archivo; si no, la validación sería engañosamente buena.

## 7.2 Aumentación de datos por simetría

Reflejar un problema en un espejo produce otro problema válido **cuya solución es la
reflexión de la original**. Es información gratis. `TopologyDataset` aplica al azar:

* espejo en x, y, z (cada uno con prob. 0.5): se invierte la rejilla y **se cambia el
  signo** de la componente de fuerza de ese eje;
* intercambio y ↔ z (si ny = nz): se intercambian también los canales $F_y$ y $F_z$.

→ hasta 16 variantes de cada muestra. ¿Por qué hay que transformar las fuerzas?
Si reflejas $x\to -x$ una pieza traccionada hacia +x, en el espejo tira hacia −x. Si
olvidaras cambiar el signo, enseñarías a la red una física falsa.

**Ejercicio:** entrena con y sin aumentación (`TopologyDataset(..., augment=False)`) y
compara la pérdida de validación.

## 7.3 La función de pérdida

`toponet/nn/losses.py` combina cuatro términos, todos calculados **solo dentro del
dominio** (los vóxeles de fuera no cuentan):

$$
\mathcal L = w_{bce}\,\mathcal L_{BCE}^{E} + w_{dice}\,\mathcal L_{Dice} + w_{vol}\,\mathcal L_{vol} + w_{tv}\,\mathcal L_{TV}
$$

### Entropía cruzada binaria ponderada por energía

Cada vóxel es una clasificación "material / vacío":

$$
\mathcal L_{BCE}^{E} = \frac{\sum_e \omega_e\,\big[-y_e\log\rho_e - (1-y_e)\log(1-\rho_e)\big]}{\sum_e\omega_e},
\qquad \omega_e = 1 + \alpha\,\hat w_e
$$

donde $\hat w_e$ es el canal 7 (energía de la pieza maciza, en [0, 1]) y $\alpha$ = 2.
**Idea:** un error en una zona que soporta mucha energía (el camino de carga) es
estructuralmente mucho más grave que en una esquina muerta. Esta ponderación es una
forma barata de introducir "conocimiento físico" en la pérdida.

Se usa `binary_cross_entropy_with_logits` (numéricamente estable: combina sigmoide
y logaritmo).

### Dice suave

$$
\mathcal L_{Dice} = 1 - \frac{2\sum_e\rho_e y_e}{\sum_e\rho_e + \sum_e y_e}
$$

Mide el **solape global** (Milletari et al. 2016). Con $V^*$ = 15 %, el 85 % de los vóxeles
son vacío: una red que lo predijera todo vacío tendría BCE bajo pero Dice pésimo.
Dice compensa este **desbalance de clases**.

### Volumen

$$
\mathcal L_{vol} = \left(\frac1N\sum_e\rho_e - V^*\right)^2
$$

Enseña a la red a respetar la consigna del canal 6. (La calibración del cap. 6.5 lo
garantiza después, pero cuanto mejor lo haga la red, menos hay que corregir.)

### Variación total

$$
\mathcal L_{TV} = \frac1N\sum_e\sum_{d\in\{x,y,z\}}|\rho_{e+\hat d} - \rho_e|
$$

Penaliza la "rugosidad": favorece superficies limpias y castiga vóxeles sueltos.
Peso pequeño (0.02): demasiado adelgaza o borra las barras finas.

### Pesos

Por defecto $w = (1, 0.5, 5, 0.02)$. Se ajustan con experimentos (7.8) y se pueden
cambiar desde la línea de comandos (`--w-dice`, `--w-vol`, `--energy-alpha`...).

### Avanzado: pérdida física (flexibilidad diferenciable)

Lo que de verdad queremos no es copiar a SIMP sino **minimizar la flexibilidad**. Se
puede añadir un término $\mathcal L_{c} = c(\rho_{pred})/c(y) - 1$, donde $c$ se
calcula con un FEM **diferenciable** en PyTorch: ensamblar $\mathbf K(\rho)$ como tensor
disperso, resolver con CG (iteraciones diferenciables o, mejor, con la regla del
adjunto: $\partial c/\partial\rho_e = -p\rho_e^{p-1}\mathbf u_e^\top\mathbf K_e\mathbf u_e$, cap. 4.3).
Esquema con una `torch.autograd.Function`:

```python
class Compliance(torch.autograd.Function):
    @staticmethod
    def forward(ctx, rho, problem):
        mesh = HexMesh(problem.domain, problem.material.nu, problem.fixed)
        r = rho.detach().cpu().numpy()[mesh.el_tuple]
        E = simp_modulus(r, 1.0, 3.0)
        res = mesh.solve(E, 1.0, problem.forces)           # FEM en NumPy
        dc = -3 * np.maximum(r, 1e-9) ** 2 * res.ce[mesh.el_tuple]
        grad = np.zeros(rho.shape); grad[mesh.el_tuple] = dc
        ctx.save_for_backward(torch.as_tensor(grad, dtype=rho.dtype))
        return rho.new_tensor(res.compliance)
    @staticmethod
    def backward(ctx, g):
        (grad,) = ctx.saved_tensors
        return g * grad, None
```

Coste: un FEM por muestra y paso de entrenamiento (≈ 50× más lento). Estrategia
habitual: preentrenar con las pérdidas baratas y luego **ajustar** (*fine-tuning*)
unas pocas épocas añadiendo la pérdida física con peso pequeño. Es uno de los
ejercicios del cap. 10.

## 7.4 Optimizador y planificación de la tasa de aprendizaje

* **AdamW** (Loshchilov & Hutter 2019): Adam con *weight decay* desacoplado
  (regularización L2 bien hecha). `lr` = 2·10⁻³, `weight_decay` = 10⁻⁴.
* **Calentamiento lineal** (2 épocas): al principio los gradientes son grandes y
  ruidosos; empezar con una tasa pequeña evita que la red "explote".
* **Decaimiento coseno** (Loshchilov & Hutter 2017) hasta `min_lr` = 5·10⁻⁵: pasos grandes
  al principio para explorar, pequeños al final para afinar.

$$
\alpha(t) = \alpha_{min} + \tfrac12(\alpha_{max}-\alpha_{min})\left(1+\cos\frac{\pi\,(t-t_w)}{T-t_w}\right)
$$

* **Recorte de gradiente** (norma ≤ 1): protege de lotes atípicos.
* **Tamaño de lote** 8: suficiente para un gradiente estable y cabe en memoria.
  Si lo aumentas, sube el `lr` proporcionalmente (regla lineal).

## 7.5 Regularización y early stopping

Con pocos cientos de muestras, el riesgo principal es el **sobreajuste**: la red
memoriza el conjunto de entrenamiento y falla con problemas nuevos. Defensas:

* aumentación (7.2) — la más eficaz;
* *dropout* 3D (10 %) en el último nivel del codificador;
* *weight decay*;
* **early stopping:** se guarda el modelo con mejor pérdida de **validación** y se
  para si no mejora en 15 épocas (`--patience`).

## 7.6 Métricas

### Geométricas (cada época, baratas)

* **IoU** (intersección sobre unión) de los diseños binarizados a 0.5.
* **MAE** de densidades.
* **Error de volumen** $|V_{pred}-V_{SIMP}|$.

### Físicas (al final, con FEM: `evaluate.py`)

```bash
python -m toponet.nn.evaluate --ckpt checkpoints/toponet_unet.pt --n 30 --refine 10
```

Para cada problema de validación, binariza la predicción, la limpia, y la analiza:

* **Gap de flexibilidad** $c_{red}/c_{SIMP} - 1$: cuánto menos rígida es la pieza de la
  red que la de SIMP con el mismo material. **Es LA métrica que importa.** (Puede ser
  negativa: SIMP no encuentra el óptimo global y a veces la red da con algo mejor.)
* **Camino de carga OK:** % de casos en que todas las cargas llegan a los apoyos.
* **Tiempo** de inferencia frente a SIMP.
* Lo mismo para el modo **híbrido** (red + `--refine` iteraciones de SIMP).

Un IoU de 0.8 puede esconder barras rotas; un gap del +5 % con el 100 % de caminos de
carga correctos es un modelo excelente.

## 7.7 Diagnóstico con las curvas de aprendizaje

`train.py` escribe `checkpoints/<nombre>_log.csv`. Dibújalo:

```python
import pandas as pd, matplotlib.pyplot as plt
d = pd.read_csv("checkpoints/toponet_unet_log.csv")
d.plot(x="epoch", y=["train_loss", "val_loss"], logy=True); plt.show()
```

| Síntoma | Diagnóstico | Remedio |
|---------|-------------|---------|
| train y val altas y planas | **Subajuste** (*underfitting*) | Red más grande (`--base 24`), más épocas, revisar `lr` |
| train baja, val sube | **Sobreajuste** | Más datos, más aumentación, más dropout/weight decay |
| pérdida oscila o da NaN | `lr` demasiado alto | Bajar `lr`, más calentamiento |
| val mejora muy despacio al final | normal con coseno | Más épocas o más datos |
| IoU bueno, gap físico malo | barras rotas / detalle fino | Más peso a la energía (`--energy-alpha`), modo híbrido, pérdida física |
| ΔV grande | consigna de volumen ignorada | Subir `--w-vol` |

## 7.8 Cómo experimentar con método

1. **Línea base:** entrena con los valores por defecto y guarda el resultado de
   `evaluate.py` (`--out resultados/base.json`).
2. **Cambia una sola cosa** cada vez (un peso de la pérdida, la arquitectura, el
   tamaño del dataset) y compara con la línea base.
3. **Ablaciones** que merece la pena hacer:
   * sin rasgos físicos (pon a cero los canales 7–8) → verás cuánto aportan;
   * sin ponderación por energía (`--energy-alpha 0`);
   * sin Dice o sin TV;
   * `base` 8 / 16 / 32; `depth` 2 / 3;
   * 160 / 320 / 640 / 1280 muestras (curva de escalado de datos).
4. Fija la semilla (`--seed`) y, si las diferencias son pequeñas, repite con 2–3
   semillas: la variabilidad entre semillas puede ser mayor que la mejora.

## 7.9 Entrenar

```bash
python -m toponet.nn.train --data data/dataset --epochs 60 --batch 8 \
       --out checkpoints/toponet_unet.pt
# reanudar si se interrumpe:
python -m toponet.nn.train --data data/dataset --epochs 60 --resume --out checkpoints/toponet_unet.pt
```

El checkpoint guarda la configuración de la red, los pesos, las métricas de
validación, los nombres de los canales y los argumentos de entrenamiento: es
autocontenido. Cualquier `.pt` que pongas en `checkpoints/` aparece en el
desplegable de la WebUI (pulsa "recargar").

**Tiempos orientativos** (640 muestras de 32×16×16): CPU de 4 núcleos ≈ 15–25 s por
época; GPU modesta ≈ 1–2 s por época.

### Resultados de referencia (modelo incluido)

Con exactamente estos comandos (640 muestras, 80 épocas, CPU de 4 núcleos, ~40 min
de datos + ~10 min de entrenamiento) se obtuvo `checkpoints/toponet_unet.pt`:

| Modo | Gap de flexibilidad vs SIMP (mediana) | Camino de carga intacto | Tiempo |
|------|----------------------------------------|-------------------------|--------|
| Solo red | +31.8 % | 90.6 % | 0.44 s |
| Híbrido (red + 10 it. SIMP) | +3.0 % | 98.4 % | 3.1 s |

Observa la diferencia entre la métrica geométrica (IoU 0.70, "parece aceptable") y
la física (1 de cada 10 diseños con una barra rota): justo lo que advertía el apartado
7.6. La ficha completa está en [`checkpoints/README.md`](../checkpoints/README.md).
Es tu línea base: usa el apartado 7.8 para superarla.

## 7.10 Escalar el sistema

* **GPU:** `--device cuda` (automático si está disponible). Con GPU puedes subir a
  64×32×32 y a decenas de miles de muestras.
* **Precisión mixta** (`torch.autocast`) en GPU: ~2× más rápido.
* **Varias resoluciones:** genera datos a 32×16×16 y 48×24×24, entrena primero con la
  pequeña y luego ajusta con la grande (*curriculum*).
* **Datos más realistas:** usa STL reales (de tus proyectos o repositorios públicos de
  piezas) con apoyos/cargas aleatorios como dominios de diseño.
* **Generación más rápida:** menos iteraciones SIMP con *warm start* desde la red
  actual (*bootstrapping*): la red genera, SIMP refina 10 iteraciones, se añade al
  dataset, se re-entrena.

---
← [6. Redes neuronales](06-redes-neuronales.md) · Siguiente: [8. Integridad y validación →](08-integridad-y-validacion.md)
