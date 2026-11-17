# Presentación de Additive 3D Engineering

La presentación de la empresa, hecha con el mismo motor que la de MRAnalyzer (reveal.js y Three.js) y con los colores del
PowerPoint original. Son 13 diapositivas con el guion en las notas del orador.

## Abrirla

`python3 comunicacion/additive3d/construir.py` deja en `comunicacion/salida/Additive3D-presentacion.html` un solo archivo
que se abre con doble clic en Chrome o Edge, sin servidor y sin internet.

- **F**: pantalla completa. **S**: vista del orador, con las notas.
- Flechas o el mando de presentar: siguiente y anterior.
- En «Simulación» (la 7), el primer avance le da al play y la simulación corre sola (unos 30 s). Con las teclas **1** a
  **6**, o tocando una etapa, se salta a esa etapa y se queda parada en ella. El siguiente avance pasa de diapositiva.
- En la última, el primer avance cambia al cierre («Ayúdanos a mejorar la medicina.»).

`construir.py artefacto` prepara en `salida/artefacto-additive3d` la copia para publicarla como página en línea.

## Cambiarla

| Qué | Dónde |
| --- | --- |
| Textos, orden de las diapositivas y notas | `presentacion.html` |
| Colores, tamaños y animaciones | `estilos.css` |
| Cerebro en 3D y simulación | `escena.js` |
| Cambio de diapositiva, contadores y dibujo de la red neuronal | `app.js` |
| Fotos y cerebro | `herramientas/preparar.py` y `herramientas/cerebro_secciones.py` |

Para verla mientras se cambia: `python -m http.server` en `comunicacion/` y abrir
`http://localhost:8000/additive3d/presentacion.html`. Después, `construir.py capturas` saca una imagen de cada diapositiva
en `salida/capturas-additive3d` para revisarlas.

## De dónde sale cada cosa

- Los textos y las fotos, del PowerPoint «Additive 3D Engineering». La foto de la impresora de hidrogel es una imagen
  generada, no una foto del prototipo.
- El cerebro es real: lo hizo MRAnalyzer con la resonancia pública «MRHead» de 3D Slicer, y sus 27 secciones las separó la
  red SynthSeg. Los cortes de la simulación y el de la diapositiva de la red neuronal son de esa misma resonancia. No hay
  datos de pacientes.
- El molde de la simulación es una caja de ejemplo, no un molde de fabricación.
- La diapositiva de protección de datos cuenta lo que hace MRAnalyzer al importar un estudio con la anonimización
  activada (`mranalyzer/anonimizar.py`). El programa guarda en el equipo, cifrada, la correspondencia entre el
  identificador y el nombre real: quien tenga ese equipo puede deshacerla. Si «sin trazabilidad» tiene que valer también
  para ese equipo, hay que no guardar esa correspondencia.
- La tipografía es Inter (licencia OFL, en `fuentes/`).
- Los textos pasan por la skill `clean-user-facing-text`, como el resto de `comunicacion/`.
