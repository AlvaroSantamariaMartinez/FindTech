// @ts-check
import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import sitemap from '@astrojs/sitemap';

// https://astro.build/config
export default defineConfig({
  // ⚠️ IMPORTANTE PARA GITHUB PAGES:
  // - Cambia "tu-usuario" por tu usuario real de GitHub.
  // - Si el repo se llama "ai-radar" -> el sitio vive en /ai-radar (usa el `base` de abajo).
  // - Si el repo se llama "tu-usuario.github.io" -> borra la línea `base` y pon base: '/'.
  site: 'https://FindTech.io',
  base: '/ai-radar',

  integrations: [sitemap()],

  vite: {
    plugins: [tailwindcss()],
  },

  markdown: {
    // Resaltado de sintaxis nativo con Shiki. github-dark encaja con la estética.
    shikiConfig: {
      theme: 'github-dark',
      wrap: true,
    },
  },
});
