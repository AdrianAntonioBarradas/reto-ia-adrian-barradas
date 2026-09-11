# Arquitectura

## Vista general

```
                    Plataforma Reto IA (o cualquier cliente Open Responses)
                                      │
                                      │  POST {base}/responses
                                      │  Authorization: Bearer <clave>
                                      ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  app/openresponses/  ·  FRONTERA DE TRADUCCIÓN                  │
    │  Permisivo al entrar, estricto al salir. Nada debajo de esta    │
    │  línea sabe que este protocolo existe.                          │
    └─────────────────────────────────────────────────────────────────┘
                                      │  list[Turn]
                                      ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  app/agent/policy.py  ·  COMPUERTA DE POLÍTICA                  │
    │  Corre ANTES del modelo. Compensación, contacto, motivos de     │
    │  salida → respuesta directa, cero llamadas al LLM.              │
    │  Texto con forma de instrucción → se marca, no se bloquea.      │
    └─────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  app/agent/loop.py  ·  ORQUESTACIÓN                             │
    │  máx. 6 iteraciones · máx. 12 turnos de historia                │
    │                                                                  │
    │    ┌──────────────┐   tool_use    ┌────────────────────────┐    │
    │    │ app/llm/     │ ────────────► │ app/tools/  (4, sólo   │    │
    │    │ LLMAdapter   │ ◄──────────── │ lectura, tipadas)      │    │
    │    └──────────────┘  tool_result  └────────────────────────┘    │
    │      Protocol:                       get_profile                │
    │      · anthropic (SDK nativo)        search_experience ──┐      │
    │      · openai_compatible             get_project         │      │
    │        (Google/Cerebras/Groq)        list_skills         │      │
    └──────────────────────────────────────────────────────────┼──────┘
                                                               ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  app/retrieval/  ·  ESCALERA (RETRIEVAL_MODE)                   │
    │                                                                  │
    │    context     sin recuperación, perfil completo en el prompt   │
    │    structured  sólo herramientas deterministas                  │
    │    dense       coseno sobre embeddings          ┐               │
    │    hybrid      dense + BM25 → RRF               ┘ ← producción  │
    └─────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  app/knowledge/  ·  CORPUS                                      │
    │  data/canonical/*.yaml  →  135 chunks semánticos                │
    │  Los YAML son la fuente de verdad; los chunks son un índice     │
    │  derivado y se pueden borrar y reconstruir sin perder nada.     │
    └─────────────────────────────────────────────────────────────────┘
```

## Las tres separaciones que importan

**Protocolo ↔ agente.** `app/openresponses/` traduce en ambos sentidos y nada más.
El agente no sabe qué protocolo lo está sirviendo, y el protocolo no sabe cómo se
produce una respuesta. Esto es lo que permite que las pruebas de contrato usen un
agente falso y que las pruebas del agente usen un LLM falso.

**Verdad ↔ permiso.** Lo que *es cierto* vive en `data/canonical/` y se consulta con
herramientas. Lo que *se puede decir* vive en la compuerta de política y en el prompt
por capas. Mezclarlos es cómo se acaba con un prompt de tres mil palabras que nadie se
atreve a tocar.

**Fuente de verdad ↔ índice.** Los YAML son la fuente; chunks y embeddings son
derivados. Reindexar es seguro por construcción: `build_chunks()` se puede correr de
cero en cualquier momento.

## Flujo de una pregunta

Tomando *"¿Ha trabajado con Kubernetes en producción?"*:

1. **Transporte.** `parse_transcript` normaliza el `input` —cadena suelta o arreglo de
   items con partes de contenido— a una lista de turnos.
2. **Política.** No coincide con ningún patrón de rechazo ni de inyección. Pasa.
3. **Prompt.** Cuatro capas de markdown desde `agent/prompts/`, más las instrucciones
   del operador si el registro las incluyó, subordinadas a la política.
4. **Modelo.** Pide `search_experience("Kubernetes producción")`.
5. **Recuperación.** BM25 y coseno en paralelo sobre 135 chunks (~4 ms), fusión RRF.
   El primer resultado es `skill:cloud_devops:Kubernetes / EKS`, cuyo texto ya dice
   *"nivel LEARNING. NO tiene experiencia profesional con esto"*.
6. **Respuesta.** El modelo responde que no, que lo está aprendiendo.
7. **Telemetría.** Se registra la categoría, los IDs de evidencia, las herramientas
   llamadas y la latencia. **Nunca el contenido de la conversación.**

## Chunking

Escrito a mano, no un divisor por ventanas de tokens, porque el chunking cambia la
calidad de recuperación:

- **Unidades semánticas:** un logro, un proyecto, una habilidad, un bloque educativo.
- **Texto autocontenido:** cada chunk nombra su propio sujeto. `"Redujo la carga
  operativa"` es inútil recuperado solo; `"Cicada — Ingeniero de Software: automatizó
  procesos de liquidación… redujo la carga operativa"` responde por sí mismo. Una
  prueba verifica que ningún chunk empiece con un pronombre suelto.
- **Prefijo de contexto antes de embeber:** la forma barata de *contextual retrieval*.
- **Dos granularidades para habilidades:** una por categoría (para "¿qué sabe de IA?")
  y una por habilidad individual (para "¿sabe Kubernetes?"). La segunda existe porque
  la primera falló de forma medible; ver DEC-011.
- **El matiz viaja con la afirmación.** Un logro `FAMILIAR` lleva su `MATIZ
  IMPORTANTE` dentro del mismo chunk, y un proyecto lleva su autoría en el cuerpo del
  texto, no sólo en metadatos: el modelo puede no ver nada más.

## Operación

| Aspecto | Cómo está resuelto |
|---|---|
| Salud | `GET /health` hace ping profundo y responde **503**, no 200 con bandera, para que un despliegue roto no se promueva |
| Migraciones | N/A — no hay base de datos (DEC-002) |
| Secretos | Variables de entorno; `.env.example` es el contrato y una prueba falla si lleva un valor real |
| Reintentos | 429 y 5xx con backoff y jitter, respetando `Retry-After` |
| Techos | 6 iteraciones de herramienta, 12 turnos de historia, tokens de salida acotados, timeout por petición |
| Trazabilidad | IDs de evidencia y recuperadores usados en cada respuesta y en los logs |
| Fallo | Un error del agente devuelve un objeto `failed`, no un 500: una UI de chat puede renderizar el primero |

## Lo que no se construyó, a propósito

- **Streaming SSE.** El agente Guía confirmó que no está especificado como obligatorio
  y recomendó explícitamente el camino no-streaming primero. Queda como extensión.
- **Reranker.** Diseñado como etapa opcional; con recall 0.879 sobre 135 chunks no es
  el cuello de botella.
- **Base de datos.** DEC-002.
- **Estado de conversación.** DEC-006: la plataforma reenvía la transcripción.
