# FindTech

- `mranalyzer/` es el proyecto principal: el programa MRAnalyzer, con su propio repositorio git e historial. Para desarrollar, probar y empaquetar, sigue su `README.md`. Lo excluye el git de FindTech (`.git/info/exclude`).
- `comunicacion/` contiene la presentación y el dosier para inversores de MRAnalyzer. Para tocarlos, usa la skill `comunicacion-mranalyzer`.
- `entrega/` guarda los paquetes firmados del programa para el usuario. No va a git y nunca se borran de ella las copias de las claves.
- La raíz (`src/`, `public/`, `astro.config.mjs`) es la web de FindTech, hecha con Astro.

## Normas

- Responder en español. En Python, `encoding="utf-8"`.
- Nunca subir a git claves privadas (`*.pem`) ni datos de pacientes.
- Todo texto para leer (diapositivas, notas del orador, dosier, LEEME y textos de la web) pasa por la skill `clean-user-facing-text`. No se usa con código y no sirve para ocultar el uso de IA cuando hay que declararlo.
