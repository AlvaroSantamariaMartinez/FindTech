# AIRadar

Blog estático de noticias de IA y radar de repositorios de GitHub. Construido con
**Astro + Tailwind CSS v4**, dark mode nativo y resaltado de sintaxis. Se despliega
gratis en **GitHub Pages**.

## Requisitos

- Node.js 20 o superior.

## Desarrollo local

```bash
npm install
npm run dev      # http://localhost:4321
npm run build    # genera /dist
npm run preview  # sirve /dist localmente
```

## Publicar un artículo nuevo

Solo tienes que crear un archivo `.md` dentro de `src/content/articulos/`.
Convención de nombre: `AAAA-MM-DD-slug-del-titulo.md`.

Frontmatter mínimo:

```yaml
---
titulo: "Título del artículo"
descripcion: "Resumen de una o dos frases para las tarjetas y el SEO."
fecha: 2026-08-05
tags:
  - LLMs
  - Herramientas
destacado: false   # true => aparece en el Hero
borrador: false    # true => no se publica
---

Cuerpo del artículo en Markdown. Los bloques de código se resaltan solos:

​```python
print("hola")
​```
```

Etiquetas disponibles: `LLMs`, `Computer Vision`, `Herramientas`,
`Investigación`, `Agentes`, `Open Source`, `Hardware`, `Ética`. (Amplía la lista
en `src/content.config.ts`.)

## Actualizar el radar de repos

Edita `src/data/repos.json`. Cada entrada necesita `id`, `nombre`, `descripcion`,
`lenguaje`, `estrellas` y `url`. Este archivo es el que puede regenerar tu script
diario automáticamente.

## Despliegue en GitHub Pages (una sola vez)

1. En `astro.config.mjs`, pon tu `site` y `base` reales (instrucciones en el
   propio archivo).
2. Sube el proyecto a un repositorio de GitHub.
3. En el repo: **Settings → Pages → Build and deployment → Source → GitHub Actions**.
4. Haz push a `main`. El workflow `.github/workflows/deploy.yml` compila y publica.

A partir de ahí, **cada vez que subas un `.md` nuevo a `main`, el sitio se
reconstruye y despliega solo.**
