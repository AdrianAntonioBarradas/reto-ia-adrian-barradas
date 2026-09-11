# Conformidad con Open Responses

Medida con el **tester oficial de la especificación**, no con pruebas propias, contra
el endpoint desplegado:

```bash
npx tsx bin/compliance-test.ts \
  --base-url https://<host>/v1 --api-key $AGENT_API_KEY --model cv-agent
```

(El repositorio de Open Responses documenta `bun run test:compliance`; corre igual con
`npx tsx` y no hace falta instalar bun.)

## Resultado

**8 de 10 pruebas HTTP.** Las 7 restantes del total de 17 son de transporte WebSocket.

| Prueba | Estado | Nota |
|---|---|---|
| `basic-response` | ✅ | |
| `multi-turn` | ✅ | |
| `system-prompt` | ✅ | |
| `assistant-phase` | ✅ | |
| `image-input` | ✅ | |
| `response-output-phase-schema` | ✅ | |
| `streaming-response` | ✅ | SSE con la secuencia completa de eventos |
| `tool-calling` | ✅ | Herramientas del cliente devueltas como `function_call` |
| `compact-response` | ❌ | `/responses/compact` no implementado |
| `compact-missing-model` | ❌ | idem |
| 7 × `websocket-*` | ❌ | Transporte WebSocket no implementado |

`docs/compliance-results.json` tiene la salida cruda.

## Por qué esto importa más que las pruebas propias

La primera corrida dio **1 de 17**.

En ese momento `tests/api/` ya tenía doce pruebas de contrato y **todas pasaban**. No
servían de nada: la misma lectura incompleta de la especificación escribió las pruebas
y la implementación. Una prueba escrita desde tu propia lectura sólo puede confirmar
esa lectura.

Lo que faltaba: **23 de los 31 campos requeridos** del objeto de respuesta. El esquema
no tiene ninguna propiedad opcional, cosa que leer la prosa no deja ver.

| Corrida | HTTP | Qué cambió |
|---|---|---|
| 1 | 1/10 | estado inicial |
| 2 | 6/10 | los 31 campos requeridos del objeto de respuesta |
| 3 | 7/10 | streaming SSE |
| 4 | **8/10** | herramientas del cliente + normalizar `tools` al esquema de respuesta |

El último fallo fue instructivo: la suite declara una herramienta sin `strict`, y
devolver la declaración del cliente tal cual falló con `tools.0.strict: Invalid input`.
Los esquemas de herramienta de *petición* y de *respuesta* no son la misma forma, y
suponer que sí porque los nombres de campo coinciden es un error fácil de cometer.

## Lo que queda fuera, y por qué

**Compactación (`/responses/compact`).** Comprime una conversación larga del lado del
servidor. Este agente no guarda estado —la plataforma reenvía la transcripción en cada
turno (DEC-006)— y una conversación sobre un CV no crece hasta necesitarlo.

**Transporte WebSocket.** Siete pruebas. Es un transporte alterno completo con su
propio ciclo de vida, reconexión y desalojo de caché. El agente Guía confirmó que ni
siquiera SSE es obligatorio, así que WebSocket queda claramente fuera del alcance.

**Streaming, con una salvedad honesta.** La prueba pasa y los eventos son válidos,
pero el adaptador devuelve el turno completo: los deltas son porciones reales de la
respuesta real, no tokens según los produce el modelo. Un cliente que renderiza
progresivamente ve texto progresivo; lo que no ve es latencia hasta el primer token
reducida. Está anotado en `app/openresponses/stream.py`, donde vive el código.
