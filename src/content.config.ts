import { defineCollection, z } from 'astro:content';
import { glob, file } from 'astro/loaders';

// ─────────────────────────────────────────────────────────────
// Colección "articulos": cada .md dentro de src/content/articulos
// se convierte en un artículo. El frontmatter se valida contra
// este esquema en tiempo de build: si falta un campo o escribes
// mal un tag, el build falla con un error claro.
// ─────────────────────────────────────────────────────────────
const articulos = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/articulos' }),
  schema: ({ image }) =>
    z.object({
      titulo: z.string(),
      descripcion: z.string(),
      fecha: z.coerce.date(),
      // Miniatura: ruta relativa a una imagen dentro de la carpeta del artículo,
      // o una URL externa. Opcional: si no hay, se usa un fondo generado.
      imagen: image().optional(),
      imagenExterna: z.string().url().optional(),
      // Etiquetas visuales. Amplía la lista según tus categorías.
      tags: z
        .array(
          z.enum([
            'LLMs',
            'Computer Vision',
            'Herramientas',
            'Investigación',
            'Agentes',
            'Open Source',
            'Hardware',
            'Ética',
          ])
        )
        .default([]),
      // Marca true para que aparezca en el Hero (solo el más reciente se usa).
      destacado: z.boolean().default(false),
      // Marca true mientras escribes: los borradores no se publican.
      borrador: z.boolean().default(false),
    }),
});

// ─────────────────────────────────────────────────────────────
// Colección "repos": un único JSON con los repositorios del radar.
// Puedes editarlo a mano o dejar que tu script diario lo regenere.
// ─────────────────────────────────────────────────────────────
const repos = defineCollection({
  loader: file('./src/data/repos.json'),
  schema: z.object({
    id: z.string(),
    nombre: z.string(), // "usuario/repo"
    descripcion: z.string(),
    lenguaje: z.string(),
    estrellas: z.number(),
    url: z.string().url(),
  }),
});

export const collections = { articulos, repos };
