# Checkpoints

Cualquier `*.pt` de esta carpeta aparece en el desplegable del plugin
"TopoNet U-Net 3D (tu red)" de la WebUI (pulsa *recargar* tras añadir uno).

## `toponet_unet.pt` — modelo preentrenado incluido

Entrenado en esta misma configuración para que la aplicación funcione desde el
primer momento. Tu objetivo es superarlo (ver `guia/07-sistema-entrenamiento.md`
y los ejercicios del capítulo 10).

| | |
|---|---|
| Arquitectura | U-Net 3D residual, `base=16`, `depth=3`, GroupNorm + SiLU, dropout 0.1 |
| Parámetros | 1 469 841 |
| Entrada | 9 canales (`toponet/nn/features.py`), rejilla de entrenamiento 32×16×16 |
| Datos | 640 problemas aleatorios resueltos con SIMP (50 it., proyección); 576 train / 64 val |
| Entrenamiento | 80 épocas, AdamW lr 2e-3, calentamiento 2 épocas + coseno, lote 8, aumentación por espejos |
| Hardware | CPU de 4 núcleos, ≈ 7 s por época (≈ 10 min en total) |

Comando exacto:

```bash
python -m toponet.nn.generate_data --n 640 --out data/dataset --workers 4 --simp-iters 50
python -m toponet.nn.train --data data/dataset --epochs 80 --threads 4 --out checkpoints/toponet_unet.pt
```

### Métricas de entrenamiento (última época, validación)

IoU 0.697 · MAE 0.104 · error de volumen 0.010 · pérdida train 0.325 / val 0.375
(curvas completas en `toponet_unet_log.csv`). La pérdida de validación seguía
bajando muy despacio: más datos deberían ayudar más que más épocas.

### Validación física (FEM) sobre los 64 problemas de validación

`python -m toponet.nn.evaluate --n 64 --refine 10` → `toponet_unet_eval.json`

| Modo | Gap de flexibilidad vs SIMP (mediana) | Camino de carga intacto | Tiempo (mediana) |
|------|----------------------------------------|-------------------------|------------------|
| Solo red | +31.8 % | 90.6 % | 0.44 s |
| Solo red + TTA | +28.0 % | 89.1 % | 0.49 s |
| **Híbrido (red + 10 it. SIMP)** | **+3.0 %** | **98.4 %** | 3.1 s |
| SIMP (50 it., referencia) | 0 % | — | ≈ 13 s* |

\* Medido durante la generación del dataset (1 hilo por proceso, 4 procesos a la
vez), así que la comparación de tiempos es solo orientativa.

**Lectura honesta:** la red sola da en menos de medio segundo una topología
razonable, pero en ~1 de cada 10 problemas deja algún miembro cortado y en la
mediana es un 30 % menos rígida que SIMP. El modo **híbrido** recupera casi toda la
calidad (3 % de diferencia, 98 % de caminos de carga intactos) en una fracción del
tiempo de SIMP. Es exactamente el comportamiento que describe la literatura
(Woldseth et al., 2022) y la razón por la que la WebUI usa el híbrido por defecto
(`refine_iters = 10`). El capítulo 8 de la guía explica por qué, y el 10, cómo mejorarlo.

Cómo leer el gap: un +inf % significa camino de carga roto (diseño inválido); los
valores negativos ocurren cuando la red encuentra un diseño más rígido que SIMP.

## Archivos

* `toponet_unet.pt` — pesos + configuración + metadatos (autocontenido)
* `toponet_unet_log.csv` — métricas por época
* `toponet_unet_args.json` — argumentos de entrenamiento
* `toponet_unet_eval.json` — validación física por problema
* `*_state.pt` — estado para `--resume` (no se versiona)
