import rss from '@astrojs/rss';
import { getCollection } from 'astro:content';

export async function GET(context) {
  const articulos = await getCollection('articulos', ({ data }) => !data.borrador);
  return rss({
    title: 'AIRadar — Noticias de IA',
    description: 'Noticias de IA y radar de repositorios open source.',
    site: context.site,
    items: articulos
      .sort((a, b) => b.data.fecha.getTime() - a.data.fecha.getTime())
      .map((a) => ({
        title: a.data.titulo,
        description: a.data.descripcion,
        pubDate: a.data.fecha,
        link: `/articulos/${a.id}/`,
      })),
  });
}
