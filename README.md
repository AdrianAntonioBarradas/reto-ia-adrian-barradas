# Agente de CV — Adrián Barradas

Agente conversacional sobre una trayectoria profesional, expuesto como endpoint
compatible con **Open Responses**. Construido para el Reto IA Banorte.

> **La idea central:** la honestidad del agente es un dato estructurado, no un párrafo
> del prompt. Cada habilidad lleva su nivel real de dominio y cada proyecto lleva su
> autoría, así que el agente dice *"está aprendiendo Kubernetes"* y no *"tiene
> experiencia en Kubernetes"* porque afirmar lo segundo requeriría contradecir la
> evidencia recuperada, no sólo rellenar un hueco.

```
POST /v1/responses                 contrato Open Responses
GET  /health                       503 si falta una dependencia, no 200 con bandera
GET  /.well-known/agent-card.json  tarjeta A2A: registro en un solo pegado
```

---

## Qué hace, en cuatro respuestas reales

```
¿Ha trabajado con Kubernetes en producción?
  → No. Kubernetes/EKS está en su lista de temas que está aprendiendo actualmente,
    no tiene experiencia profesional ni de producción con eso. Donde sí tiene
    experiencia sólida es en Docker, Git, GitHub Actions y Linux.

Necesitamos alguien con Azure. ¿Encaja?
  → No, Azure no aparece en su perfil en absoluto, ni siquiera como algo que esté
    aprendiendo. Su experiencia en cloud está del lado de AWS.

¿Él construyó el bot de producción del Instituto Newman?
  → No, ese bot lo construyó el socio de Ayari Tech, no Adrián. Su trabajo ahí fue
    el track de research.

¿Cuánto ganaba en Cicada?
  → No tengo información sobre temas de compensación, y no es algo que corresponda
    a este agente.
```

Las tres primeras son respuestas del modelo apoyadas en evidencia. La cuarta **nunca
llega al modelo**: la resuelve la compuerta de política, y el dato no existe en el
corpus.

---

## Arquitectura en un párrafo

Una API en FastAPI traduce Open Responses hacia un dominio interno que no sabe que ese
protocolo existe. Una compuerta de política corre antes del modelo y resuelve
directamente lo que no debe generarse. El bucle del agente llama a **cuatro
herramientas tipadas de sólo lectura** sobre un corpus curado de 135 chunks; la
recuperación es **híbrida** (coseno denso + BM25, fusionados con Reciprocal Rank
Fusion) y corre en memoria en ~4 ms. El proveedor de LLM está detrás de un Protocol
con dos implementaciones.

Diagrama y detalle: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Decisiones que vale la pena defender

| Decisión | Por qué | Detalle |
|---|---|---|
| **Sin LangChain** | El reto evalúa el criterio detrás de las capas que un framework esconde; la traducción a Open Responses había que escribirla igual | [DEC-001](docs/DECISIONS.md#dec-001--sin-framework-de-orquestación-langchain-llamaindex) |
| **Sin base de datos** | 135 chunks estáticos que viajan en el repo; coseno exacto en 4 ms. Añadir Postgres sería complejidad que no responde a ninguna pregunta | [DEC-002](docs/DECISIONS.md#dec-002--índice-en-memoria-no-postgresql--pgvector) |
| **Privacidad en el corpus, no en el prompt** | El agente no puede revelar lo que nunca ingirió | [DEC-003](docs/DECISIONS.md#dec-003--la-frontera-de-privacidad-es-el-corpus-no-el-prompt) |
| **Honestidad como dato** | Un modelo servicial bajo presión de encaje suaviza un "no" hasta que parece un "sí" | [DEC-004](docs/DECISIONS.md#dec-004--la-política-de-honestidad-es-un-dato-estructurado-no-prosa) |
| **Contrato primero** | Una recuperación perfecta detrás de un endpoint no conforme vale cero | [DEC-005](docs/DECISIONS.md#dec-005--contrato-primero-calidad-después) |
| **Híbrido sobre denso** | Medido: recall 0.879 vs 0.818 en el mismo conjunto de casos | [DEC-008](docs/DECISIONS.md#dec-008--recuperación-híbrida-elegida-por-medición) |

---

## Evaluación

El conjunto de casos se escribió **antes** que el sistema que califica. Uno escrito
después tiende a codificar lo que el sistema ya hace en vez de lo que debería hacer.

**42 casos, 12 categorías.** Además de las habituales, tres que salen de las reglas del
propio perfil y son las que fallan en silencio: `proficiency-honesty` (nunca presentar
`LEARNING` o `FAMILIAR` como experiencia, ni bajo presión de encaje), `attribution` (no
atribuirse trabajo ajeno) y `privacy`. Los casos de honestidad llevan
`forbidden_claims` además de puntos esperados, porque calificar sólo por lo que debe
aparecer deja pasar una falsedad dicha con las palabras correctas.

**Recuperación** — sin LLM, sin tokens, sin red ([`docs/EVALUATION-RETRIEVAL.md`](docs/EVALUATION-RETRIEVAL.md)):

| Modo | Recall | MRR | p50 | p95 |
|---|---:|---:|---:|---:|
| `dense` | 0.818 | 0.745 | 5.5 ms | 10.3 ms |
| `hybrid` | **0.879** | 0.742 | 4.5 ms | 6.7 ms |

Los seis puntos de diferencia son exactamente los casos de término exacto que la
búsqueda densa falla (`ISIN`, `LocalStack`). El MRR empatado dice que híbrido encuentra
más sin degradar lo que ya ordenaba bien.

Que corra sin LLM no es un detalle: significa que puede ser una compuerta de CI, cosa
que una evaluación con modelo nunca puede permitirse.

**Respuestas** — 42 casos contra el agente real ([`docs/EVALUATION-ANSWERS.md`](docs/EVALUATION-ANSWERS.md)):

**42/42 sin ninguna afirmación falsa**, con `claude-sonnet-5` y recuperación híbrida.
Latencia p50 ~4 s, dominada por el LLM. La calificación es determinista —coincidencia
de subcadenas con conciencia de negación, sin modelo juez—: más tosca que un juez, pero
gratuita, reproducible, y **nunca inventa un aprobado**.

**Errores propios que las pruebas atraparon** — se documentan porque *"¿cómo verificas
que el agente es confiable?"* se contesta mejor con fallos reales que con una promesa.
Cuatro están en [DEC-011](docs/DECISIONS.md#dec-011--errores-propios-encontrados-por-las-pruebas),
incluido uno donde una métrica mía estaba mal calculada y reportaba el sistema **peor**
de lo que era.

---

## Correr en local

Requiere [devbox](https://www.jetify.com/devbox) y una clave de API de LLM.

```bash
devbox shell
cp .env.example .env        # y llenar AGENT_API_KEY y LLM_API_KEY
uv sync

devbox run check            # ruff + mypy strict + pytest (131 pruebas)
devbox run dev              # uvicorn en :8000
```

```bash
curl -s localhost:8000/v1/responses \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"cv-agent","input":"¿Qué experiencia tiene con Go?"}' | jq -r '.output[0].content[0].text'
```

Evaluación de recuperación (no gasta tokens):

```bash
uv run python -m scripts.eval_retrieval --write
```

---

## Configuración

Todo en [`.env.example`](.env.example), que es el contrato: cada variable documenta de
dónde sale y qué significa vacía. Una prueba falla si el archivo llega a llevar una
credencial real, y otra falla si deja de documentar exactamente lo que `Settings` lee.

Lo que más importa:

```bash
AGENT_API_KEY=      # el bearer que envía la plataforma. VACÍO = rechaza todo,
                    # en todos los entornos. No hay excepción por entorno.
LLM_PROVIDER=anthropic          # o openai_compatible
LLM_MODEL=claude-sonnet-5
RETRIEVAL_MODE=hybrid           # context | structured | dense | hybrid
```

`RETRIEVAL_MODE` es el interruptor de la escalera: un solo pipeline con cuatro modos,
no cuatro sistemas. Es lo que hace que la comparación medida sea asequible.

---

## Estructura

```
app/
  openresponses/   frontera de traducción del protocolo
  api/             /v1/responses · /health · tarjeta A2A · auth
  agent/           compuerta de política · bucle · prompts por capas
  tools/           4 herramientas tipadas de sólo lectura
  retrieval/       BM25 · denso · RRF · interruptor de modo
  knowledge/       carga del corpus · chunking semántico
  llm/             Protocol + adaptador Anthropic + compatible-OpenAI
  embeddings/      Protocol + ONNX local
agent/prompts/     el prompt del sistema, en markdown revisable
data/canonical/    la proyección pública del perfil  ← fuente de verdad
evals/cases.jsonl  42 casos, escritos antes que el sistema
scripts/           evaluación de recuperación
docs/              ARCHITECTURE · DECISIONS · SECURITY · EVALUATION · DEMO
```

---

## Seguridad

Repasado contra el **OWASP GenAI LLM Top 10 (2025)** en
[`docs/SECURITY.md`](docs/SECURITY.md), incluyendo una sección de lo que **no** está
resuelto —un inventario que sólo lista victorias no es creíble.

Lo esencial: los datos privados nunca entraron al corpus; hay cuatro herramientas de
sólo lectura y ninguna otra superficie de acción; la autenticación falla cerrado sin
excepción por entorno; y la telemetría registra IDs de evidencia y latencias, nunca el
contenido de la conversación.

---

## Créditos y alcance

Perfil profesional de Adrián Antonio Barradas Cerna. El corpus de este repositorio es
una **proyección pública** de un perfil maestro privado; los datos sensibles están
excluidos en el origen.
