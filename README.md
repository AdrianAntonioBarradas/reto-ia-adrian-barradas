# Agente de CV — Adrián Barradas

Agente conversacional sobre una trayectoria profesional, expuesto como endpoint
compatible con **Open Responses**. Construido para el Reto IA Banorte.

> **La idea central:** la honestidad del agente es un dato estructurado, no un párrafo
> del prompt. Cada habilidad lleva su nivel real de dominio y cada proyecto lleva su
> autoría, así que el agente dice *"está aprendiendo Kubernetes"* y no *"tiene
> experiencia en Kubernetes"* porque afirmar lo segundo requeriría contradecir la
> evidencia recuperada, no sólo rellenar un hueco.

```
POST /v1/responses                 contrato Open Responses (streaming y no-streaming)
GET  /health                       503 si falta una dependencia, no 200 con bandera
GET  /.well-known/agent-card.json  tarjeta A2A: registro en un solo pegado
```

| | |
|---|---|
| **8 / 10** pruebas HTTP del tester **oficial** de Open Responses, contra el endpoint desplegado | [EVALUACION](docs/EVALUACION.md#conformidad-con-open-responses) |
| **42 / 42** casos sin ninguna afirmación falsa, en cuatro modos de recuperación y dos modelos | [EVALUACION](docs/EVALUACION.md#respuestas) |
| **0.879** de recall en recuperación híbrida, frente a 0.818 de sólo densa | [EVALUACION](docs/EVALUACION.md#recuperación) |
| **159** chunks · **145** pruebas · **45** casos de evaluación | corpus `a13f9815`, 2026-09-11 |

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

## La documentación

Cuatro documentos, un tema cada uno. **Un hecho vive en un solo lugar** y los demás
enlazan: es la única defensa contra que una cifra se desactualice en silencio en seis
sitios a la vez.

| Documento | Qué contiene |
|---|---|
| [**ARQUITECTURA.md**](docs/ARQUITECTURA.md) | El diagrama, las **15 decisiones** con su justificación y su medición, lo que no se construyó a propósito, el trabajo pendiente, y un anexo con las restricciones del reto |
| [**ESQUEMAS.md**](docs/ESQUEMAS.md) | Los ocho contratos: corpus YAML, manifiesto, modelo de chunk, Open Responses, tarjeta A2A, herramientas, entorno, casos de evaluación |
| [**EVALUACION.md**](docs/EVALUACION.md) | Cómo se mide y qué salió: recuperación, respuestas, la escalera, comparación de modelos, conformidad. Cada tabla con su modelo, modo, fecha y versión del corpus |
| [**POLITICAS.md**](docs/POLITICAS.md) | La política de honestidad como dato, los escenarios que la verifican, y el repaso completo contra el OWASP GenAI LLM Top 10 (2025 → 2026) |

---

## Arquitectura en un párrafo

Una API en FastAPI traduce Open Responses hacia un dominio interno que no sabe que ese
protocolo existe. Una compuerta de política corre antes del modelo y resuelve
directamente lo que no debe generarse. El bucle del agente llama a **cuatro herramientas
tipadas de sólo lectura** sobre un corpus curado; la recuperación es una **escalera de
cuatro modos** en un solo pipeline, y corre en memoria en ~4 ms. El proveedor de LLM
está detrás de un Protocol con dos implementaciones.

---

## Decisiones que vale la pena defender

| Decisión | Por qué |
|---|---|
| [**Sin LangChain**](docs/ARQUITECTURA.md#dec-001--sin-framework-de-orquestación-langchain-llamaindex) | El reto evalúa el criterio detrás de las capas que un framework esconde; la traducción a Open Responses había que escribirla igual |
| [**Sin base de datos**](docs/ARQUITECTURA.md#dec-002--índice-en-memoria-no-postgresql--pgvector) | Un corpus estático que viaja en el repo; coseno exacto en 4 ms. Postgres sería complejidad que no responde a ninguna pregunta |
| [**Privacidad en el corpus, no en el prompt**](docs/ARQUITECTURA.md#dec-003--la-frontera-de-privacidad-es-el-corpus-no-el-prompt) | El agente no puede revelar lo que nunca ingirió |
| [**Honestidad como dato**](docs/ARQUITECTURA.md#dec-004--la-política-de-honestidad-es-un-dato-estructurado-no-prosa) | Un modelo servicial bajo presión de encaje suaviza un "no" hasta que parece un "sí" |
| [**Contrato primero**](docs/ARQUITECTURA.md#dec-005--contrato-primero-calidad-después) | Una recuperación perfecta detrás de un endpoint no conforme vale cero |
| [**Híbrido sobre denso**](docs/ARQUITECTURA.md#dec-008--recuperación-híbrida-elegida-por-medición) | Medido: recall 0.879 vs 0.818 en el mismo conjunto de casos |
| [**Producción sin recuperación**](docs/ARQUITECTURA.md#dec-014--el-modo-de-producción-es-context-porque-eso-dice-la-medición) | La línea base ganó la medición end-to-end. Enviar lo que mis datos dicen que es peor habría vuelto decorativa la medición |
| [**Correr la especificación ejecutable**](docs/ARQUITECTURA.md#dec-015--correr-la-especificación-ejecutable-no-mi-lectura-de-ella) | 1/17 la primera vez, con mis doce pruebas propias en verde |
| [**Un contenedor en Railway**](docs/ARQUITECTURA.md#dec-013--despliegue-en-railway-y-el-archivo-de-configuración-que-ya-no-sirve) | Sin estado, sin base de datos; la latencia la domina el LLM |

**El hilo que las conecta**, y que aparece siete veces en el registro: *el instrumento de
medición falló más veces que el sistema medido.* Los errores propios que las pruebas
atraparon están en
[DEC-011](docs/ARQUITECTURA.md#dec-011--errores-propios-encontrados-por-las-pruebas),
incluido uno donde una métrica mía reportaba el sistema **peor** de lo que era.

---

## Correr en local

Requiere [devbox](https://www.jetify.com/devbox) y una clave de API de LLM.

```bash
devbox shell
cp .env.example .env        # y llenar AGENT_API_KEY y LLM_API_KEY
uv sync

devbox run check            # ruff + mypy strict + pytest (145 pruebas)
devbox run dev              # uvicorn en :8000
```

```bash
curl -s localhost:8000/v1/responses \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"cv-agent","input":"¿Qué experiencia tiene con Go?"}' | jq -r '.output[0].content[0].text'
```

## Probar el agente desplegado

Cuatro capas, de la más barata a la más cara — comandos completos en
[EVALUACION § Cómo correrlo](docs/EVALUACION.md#cómo-correrlo):

1. `./scripts/smoke_test.sh` — compuerta de release, sale != 0 al primer fallo.
2. El tester oficial de conformidad.
3. Los 45 casos contra el agente real.
4. **La interfaz de chat de la propia plataforma**, que es la de mayor fidelidad: es
   donde se va a evaluar, ejercita la ruta de integración real y funciona en un teléfono.

No hay un front end propio en este repositorio **a propósito**: sería una segunda
superficie que nadie va a usar, con la clave de API expuesta en el navegador o un proxy
extra que mantener, y el reto advierte explícitamente contra añadir piezas que no
responden a una necesidad real.

### Operación

```bash
railway up                      # desplegar (el build baja el modelo, ~3 min)
railway down --yes              # detener: quita el despliegue, conserva servicio y variables
railway logs                    # logs de ejecución
```

---

## Configuración

Todo en [`.env.example`](.env.example), que **es el contrato**: cada variable documenta
de dónde sale y qué significa vacía. Una prueba falla si el archivo llega a llevar una
credencial real, y otra falla si deja de documentar exactamente lo que `Settings` lee.
Tabla completa en [ESQUEMAS § Entorno](docs/ESQUEMAS.md#7-entorno).

```bash
AGENT_API_KEY=      # el bearer que envía la plataforma. VACÍO = rechaza todo,
                    # en todos los entornos. No hay excepción por entorno.
LLM_PROVIDER=anthropic          # o openai_compatible
LLM_MODEL=claude-sonnet-5
RETRIEVAL_MODE=context          # context | structured | dense | hybrid
```

`RETRIEVAL_MODE` es el interruptor de la escalera: un solo pipeline con cuatro modos, no
cuatro sistemas. Es lo que hace asequible la comparación medida — y el default es
`context` porque **ganó esa comparación**.

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
data/manifests/    SHA-256 por archivo + digest del corpus
evals/cases.jsonl  45 casos, escritos antes que el sistema
scripts/           evaluación, manifiesto, calentamiento del modelo, humo
docs/              ARQUITECTURA · ESQUEMAS · EVALUACION · POLITICAS · DEMO
```

---

## Seguridad

Repasado contra el **OWASP GenAI LLM Top 10**, con el mapeo a la edición **2026** en
[`docs/POLITICAS.md`](docs/POLITICAS.md) —incluido el re-alcance de *System Prompt
Leakage* a *Hidden Context Exposure*, que en modo `context` abarca el corpus entero—,
y con una sección de lo que **no** está resuelto: un inventario que sólo lista victorias
no es creíble.

Lo esencial: los datos privados nunca entraron al corpus; hay cuatro herramientas de sólo
lectura y ninguna otra superficie de acción; la autenticación falla cerrado sin excepción
por entorno; y la telemetría registra IDs de evidencia y latencias, nunca el contenido de
la conversación.

---

## Créditos y alcance

Perfil profesional de Adrián Antonio Barradas Cerna. El corpus de este repositorio es una
**proyección pública** de un perfil maestro privado; los datos sensibles están excluidos
en el origen.
