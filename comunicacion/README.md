# Comunicación de MRAnalyzer

Presentaciones y dosieres del proyecto. El producto está en `../mranalyzer`; esta carpeta solo lo cuenta.

| Qué | Fuente | Se genera en |
| --- | --- | --- |
| Presentación holográfica (reveal.js + Three.js, guion en las notas) | `presentacion/` | `salida/MRAnalyzer-presentacion-<versión>.zip` |
| Dosier para inversores (A4) | `dosier/dosier.html` + `dosier.css` | `salida/MRAnalyzer-dosier-<versión>.pdf` |
| Cifras de los dos | `datos.json` | — |

`salida/` no se guarda en git: se vuelve a generar.

## Poner al día

```bash
cd FindTech
python3.13 comunicacion/actualizar.py     # cifras: versión, líneas de código y pruebas que pasan (~3 min)
python3.13 comunicacion/generar.py todo   # renders 3D del dosier, PDF y zip de la presentación
python3.13 comunicacion/generar.py capturas  # una imagen por diapositiva en salida/capturas, para revisarlas
```

- **Cifras automáticas** (`actualizar.py`): versión, fecha, líneas de Python y de JavaScript propio (sin `vendor/`) y pruebas que pasan. Si alguna prueba falla, se para: no se presume de pruebas rotas.
- **Cifras manuales** (`datos.json` → `manuales`): cada una con su fuente. Una cifra nueva necesita una fuente.
- En los HTML, cualquier elemento con `data-dato="clave"` recibe el valor de esa clave. En los contadores animados, el valor va en `data-hasta`.
- Lo que va entre corchetes (`[Nombre]`, `[€ __]`) son datos que solo puede poner el equipo: nombres, mercado, ronda, precios y competidores.

## Modelos 3D de la presentación

`presentacion/assets/` contiene las mallas reales generadas por MRAnalyzer a partir de muestras públicas de 3D Slicer (TAC «CTChest» y RM «MRHead»), nunca de pacientes. Para regenerarlas, sigue `recursos/construir_assets.py`.

## Abrir la presentación

Hace falta un servidor local, porque los modelos no cargan desde `file://`:

```bash
cd comunicacion/presentacion && python -m http.server 8000
```

Después abre `http://localhost:8000/presentacion.html` y pulsa **F** para pantalla completa y **S** para la vista del orador.

## Textos

Todo texto para leer (diapositivas, notas, dosier y LEEME) pasa por la skill `clean-user-facing-text` (en `.claude/skills/`). Primero se mide; solo se reescribe si la densidad sale `high`, y nunca se tocan cifras, nombres, código ni la obligación de declarar el uso de IA si la hay.
