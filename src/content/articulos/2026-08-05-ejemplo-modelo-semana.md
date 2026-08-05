---
titulo: "Claude Sonnet 5 llega con contexto de 1M de tokens y precio de derribo"
descripcion: "El nuevo modelo de Anthropic se acerca a Opus en tareas agénticas y de código, con una ventana de contexto de un millón de tokens y precio introductorio. Analizamos qué cambia para quien construye sobre la API."
fecha: 2026-08-05
imagenExterna: "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=1200&q=80"
tags:
  - LLMs
  - Herramientas
destacado: true
borrador: false
---

Anthropic ha lanzado **Claude Sonnet 5**, un modelo de clase Sonnet que estrecha
la distancia con Opus en las áreas donde antes flaqueaba: código y flujos
agénticos. La novedad no es solo de capacidad, sino de economía: durante el
periodo introductorio, el precio por millón de tokens lo sitúa entre los modelos
frontera más baratos del mercado.

## Por qué importa

La combinación de una ventana de contexto amplia y un precio bajo cambia el
cálculo para muchos proyectos. Tareas que antes exigían Opus —refactors
multi-archivo, análisis de documentos largos, agentes con muchas herramientas—
ahora caben en un presupuesto mucho menor.

> El movimiento se resume en una idea: la mayor parte de la capacidad de un
> modelo grande, a una fracción del coste y con mejor latencia.

## Puntos clave

- Modelo pensado para **coding y agentes**, con soporte de visión y uso de
  herramientas.
- Ventana de contexto amplia sin recargo por contexto largo.
- Precio introductorio por tiempo limitado antes de pasar a la tarifa estándar.

## Cómo llamarlo desde la API

Un ejemplo mínimo en Python con el SDK oficial:

```python
import os
from anthropic import Anthropic

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

respuesta = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": "Resume en 3 frases las novedades de este modelo.",
        }
    ],
)

print(respuesta.content[0].text)
```

Y el equivalente en TypeScript:

```typescript
import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic();

const respuesta = await client.messages.create({
  model: "claude-sonnet-5",
  max_tokens: 1024,
  messages: [{ role: "user", content: "Hola, Claude" }],
});

console.log(respuesta.content);
```

## Conclusión

Para quien construye productos sobre la API, Sonnet 5 es el nuevo punto de
partida por defecto: suficiente potencia para la mayoría de tareas, a un coste
que hace viables proyectos que antes no salían a cuenta.

*Fuentes: anunciado oficialmente por Anthropic. Este artículo es un resumen
original con enlaces a las fuentes primarias, no una reproducción de su
contenido.*
