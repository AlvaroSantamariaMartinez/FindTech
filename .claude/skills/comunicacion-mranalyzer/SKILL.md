---
name: comunicacion-mranalyzer
description: Poner al día la presentación holográfica o el dosier para inversores de MRAnalyzer (FindTech/comunicacion). Usar cuando el usuario pida actualizar, rehacer, exportar o revisar la presentación, el guion, el dosier, el PDF para inversores o las cifras que aparecen en ellos.
---

# Comunicación de MRAnalyzer

Todo vive en `FindTech/comunicacion/` (léete su `README.md`). El producto está en `FindTech/mranalyzer/`.

## Procedimiento

1. **Cifras.** `python3.13 comunicacion/actualizar.py` (o `--rapido` sin pasar pruebas). Si una prueba falla, arréglala en `mranalyzer/` o díselo al usuario; nunca bajes ni maquilles la cifra a mano.
2. **Cambios de contenido.** Edita `presentacion/presentacion.html` (diapositivas y `<aside class="notes">` con el guion y tiempos de unos 5 min en total) y/o `dosier/dosier.html`. Una cifra nueva:
   - va a `datos.json` → `manuales`, con su fuente (motor.log, una medición o el código);
   - se enlaza en el HTML con `data-dato="clave"`.
   No inventes cifras de mercado, equipo, precios, ronda ni competidores: déjalas entre corchetes.
3. **Textos.** Pasa la skill `clean-user-facing-text` por la prosa nueva o cambiada (mide, limpia la capa Unicode y reescribe solo si la densidad sale `high`). Respeta la tipografía española: comillas «», rayas y `--no-normalize-spaces`.
4. **Escena 3D** (si cambian los estados o la cámara): `presentacion/escena.js`, tabla `ESTADOS`, un estado por diapositiva. Para mallas nuevas, `recursos/construir_assets.py`, siempre con muestras públicas, nunca con datos de pacientes.
5. **Generar.** `python3.13 comunicacion/generar.py todo` produce los renders de `dosier/img`, el PDF y el zip en `salida/`.
6. **Revisar.**
   - Ejecuta `generar.py capturas` y mira cada `salida/capturas/dNN.png`: texto encima del holograma, cifras partidas en dos líneas, desbordes.
   - Rasteriza el PDF (`pdftoppm -r 60`) y míralo página a página.
   - Sin GPU, la escena tarda: las capturas esperan 9 s por diapositiva.
7. **Entregar.** Envía al usuario el PDF y/o el zip de `salida/`. Si te lo pide, publica la presentación como artefacto: los `.bin` se suben como `assets/<nombre>.bin.wasm`, porque `escena.js` prueba las dos extensiones.

## Reglas

- Mismas normas que el proyecto: textos en español y `encoding="utf-8"`.
- No metas en `comunicacion/` claves ni datos de pacientes.
- `mranalyzer/` es su propio repositorio git (con su historial); `comunicacion/` se guarda en el git de FindTech.
