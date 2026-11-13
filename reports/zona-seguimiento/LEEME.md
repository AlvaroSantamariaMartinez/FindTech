# Zona de seguimiento

Estudio de una zona con cámaras fijas para seguir el órgano de silicona de «Órgano real». Es solo un estudio: no cambia
nada del programa.

* `zona-seguimiento.html`: la página con la maqueta, el benchmarking y el presupuesto. Se monta con `montar.py` a
  partir de `plantilla.html`, `maqueta.jpg` y `resultados.json`.
* `simulacion_zona.py`: la simulación de la que salen las gráficas. Escribe `resultados.json`. Pide numpy, scipy y
  trimesh, y tarda unos dos minutos.
* `maqueta_blender.py`: la escena de la maqueta, para Blender 4.2. Usa el soporte de `entrega/soporte-cerebro` y la
  forma que genera `cerebro_generico.py`.

La pieza de la simulación y la de la maqueta son formas genéricas. No hay datos de pacientes.
