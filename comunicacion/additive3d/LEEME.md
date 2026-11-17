# Presentación de Additive 3D Engineering

La presentación de la empresa, hecha con el mismo motor que la de MRAnalyzer (reveal.js y Three.js) y con los colores del
PowerPoint original. Son 11 diapositivas con el guion en las notas del orador.

## Abrirla

`python3 comunicacion/additive3d/construir.py` deja en `comunicacion/salida/Additive3D-presentacion.html` un solo archivo
que se abre con doble clic en Chrome o Edge, sin servidor y sin internet.

- **F**: pantalla completa. **S**: vista del orador, con las notas.
- Flechas o el mando de presentar: siguiente y anterior.
- En «Simulación», el primer avance le da al play y la simulación corre sola (unos 30 s). Con las teclas **1** a **6**, o
  tocando una etapa, se salta a esa etapa y se queda parada en ella. El siguiente avance pasa de diapositiva.
- En la última, el primer avance cambia al cierre («Ayúdanos a mejorar la medicina.»).

## Cambiarla

| Qué | Dónde |
| --- | --- |
| Textos, orden de las diapositivas y notas | `presentacion.html` |
| Colores, tamaños y animaciones | `estilos.css` |
| Modelos 3D y simulación | `escena.js` |
| Cambio de diapositiva, contadores y etapas de la simulación | `app.js` |
| Fotos y modelos | `herramientas/preparar.py` (los saca del PowerPoint y de `../presentacion/assets`) |

Para verla mientras se cambia: `python -m http.server` en `comunicacion/` y abrir
`http://localhost:8000/additive3d/presentacion.html`. Después, `construir.py capturas` saca una imagen de cada diapositiva
en `salida/capturas-additive3d` para revisarlas.

## De dónde sale cada cosa

- Los textos y las fotos, del PowerPoint «Additive 3D Engineering». La foto de la impresora de hidrogel es una imagen
  generada, no una foto del prototipo.
- Los modelos 3D son reales: los hizo MRAnalyzer con muestras públicas de 3D Slicer (TAC «CTChest» y resonancia
  «MRHead»). No hay datos de pacientes.
- El molde de la simulación es una caja de ejemplo, no un molde de fabricación.
- La tipografía es Inter (licencia OFL, en `fuentes/`).
- Los textos pasan por la skill `clean-user-facing-text`, como el resto de `comunicacion/`.
