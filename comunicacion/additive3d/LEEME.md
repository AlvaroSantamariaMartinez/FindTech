# Presentación de Additive 3D Engineering

La presentación de la empresa, hecha con el mismo motor que la de MRAnalyzer (reveal.js y Three.js) y con los colores del
PowerPoint original. Son 13 diapositivas con el guion en las notas del orador.

## Abrirla

`python3 comunicacion/additive3d/construir.py` deja en `comunicacion/salida/Additive3D-presentacion.html` un solo archivo
que se abre con doble clic en Chrome o Edge, sin servidor y sin internet.

- **F**: pantalla completa. **S**: vista del orador, con las notas.
- Flechas o el mando de presentar: siguiente y anterior.
- En «Simulación» (la 8), cada avance pasa a la etapa siguiente y el retroceso vuelve a la anterior. Con las teclas
  **1** a **6**, o tocando una etapa, se salta a ella. Después de la última etapa, el avance pasa de diapositiva.
- En la última, el primer avance cambia al cierre («Ayúdanos a mejorar la medicina.»).
- **M**, o el altavoz del pie: quita y pone el sonido. Se recuerda para la próxima vez.

Tiene efectos de sonido: el cambio de diapositiva, cada etapa de la simulación, las neuronas de la red, el escaneo de
las gafas, los contadores, el avión del cierre (más fuerte por delante, apagado detrás del hueso, y de un altavoz a
otro) y el final. Se generan en el navegador, sin archivos de audio. El navegador no deja sonar nada hasta la primera
tecla o clic, así que la portada es muda hasta que se pasa.

`construir.py artefacto` prepara en `salida/artefacto-additive3d` la copia para publicarla como página en línea.

## Cambiarla

| Qué | Dónde |
| --- | --- |
| Textos, orden de las diapositivas y notas | `presentacion.html` |
| Colores, tamaños y animaciones | `estilos.css` |
| Cerebro y torso en 3D, simulación y realidad mixta | `escena.js` |
| Cambio de diapositiva, contadores y dibujo de la red neuronal | `app.js` |
| Efectos de sonido | `sonido.js` |
| Fotos y cerebro (portada y cierre) | `herramientas/preparar.py` y `herramientas/cerebro_secciones.py` |
| Torso, sus cortes, el corte de la red neuronal y los vasos | `herramientas/torso.py` |

En «Material de desarrollo» (la 5) la protagonista es la impresora de hidrogel; la granja de impresoras va debajo, en pequeño.

Para verla mientras se cambia: `python -m http.server` en `comunicacion/` y abrir
`http://localhost:8000/additive3d/presentacion.html`. Después, `construir.py capturas` saca una imagen de cada diapositiva
en `salida/capturas-additive3d` para revisarlas.

## De dónde sale cada cosa

- Los textos y las fotos, del PowerPoint «Additive 3D Engineering». La foto de la impresora de hidrogel es una imagen
  generada, no una foto del prototipo.
- El cerebro de la portada y del cierre es real: lo hizo MRAnalyzer con la resonancia pública «MRHead» de 3D Slicer, y
  sus secciones las separó la red SynthSeg.
- El torso de la red neuronal (la 7), la simulación (la 8) y la realidad mixta (la 9) sale del TAC de tórax público
  «CTChest» de las muestras de 3D Slicer, segmentado con TotalSegmentator: piel, pulmones, costillas, columna,
  corazón, grandes vasos, tráquea y esófago, entre otras: 18 estructuras en total. Los cortes y el corte de la red son de ese
  mismo TAC. No hay datos de pacientes.
- En la simulación, a partir de «Modelo 3D» la pieza se abre por delante: se ven las costillas, los pulmones, los
  órganos y el hueco del tórax.
- En «Realidad mixta» (la 9) no hay fotos: unas gafas escanean el torso, su gemelo digital encaja encima y el torso se
  vuelve transparente: se ven las costillas, los pulmones, los órganos y los vasos encendidos. Las gafas son unas Meta Quest 3 modeladas en la propia escena (las de la app de realidad
  aumentada). Los vasos son los del propio TAC (la aorta y sus ramas, las venas cavas y las venas pulmonares) y crecen
  desde el corazón.
- En la última, un avión de pasajeros da vueltas alrededor del coxis de la pelvis. Cuando pasa por detrás, el hueso lo
  tapa. El avión está modelado en la propia escena.
- El molde de la simulación es una caja de ejemplo, no un molde de fabricación.
- La diapositiva de protección de datos cuenta lo que hace MRAnalyzer al importar un estudio con la anonimización
  activada (`mranalyzer/anonimizar.py`). El programa guarda en el equipo, cifrada, la correspondencia entre el
  identificador y el nombre real: quien tenga ese equipo puede deshacerla. Si «sin trazabilidad» tiene que valer también
  para ese equipo, hay que no guardar esa correspondencia.
- La tipografía es Inter (licencia OFL, en `fuentes/`).
- Los textos pasan por la skill `clean-user-facing-text`, como el resto de `comunicacion/`.
