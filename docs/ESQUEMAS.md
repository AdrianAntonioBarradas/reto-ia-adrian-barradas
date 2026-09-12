# Esquemas y contratos

Los seis contratos del sistema, en un solo lugar. Antes estaban implícitos en el código
y repartidos en prosa por cuatro documentos, que es la forma más segura de que uno se
desincronice sin que nadie lo note.

Cada sección dice **quién impone el contrato** —el reto, un estándar externo, o este
proyecto— porque de eso depende cuánta libertad hay para cambiarlo.

| # | Contrato | Impuesto por | Fuente en el código |
|---|---|---|---|
| 1 | [Corpus YAML](#1-corpus-yaml) | Este proyecto | `data/canonical/*.yaml` |
| 2 | [Manifiesto del corpus](#2-manifiesto-del-corpus) | Este proyecto | `data/manifests/canonical.json` |
| 3 | [Modelo de chunk](#3-modelo-de-chunk) | Este proyecto | `app/knowledge/chunker.py` |
| 4 | [Open Responses](#4-open-responses) | La plataforma del reto | `app/openresponses/schemas.py` |
| 5 | [Tarjeta de agente A2A](#5-tarjeta-de-agente-a2a) | A2A v1.0 | `app/api/agent_card.py` |
| 6 | [Herramientas](#6-herramientas) | Este proyecto | `app/tools/cv_tools.py` |
| 7 | [Entorno](#7-entorno) | Este proyecto | `.env.example` ↔ `app/config.py` |
| 8 | [Casos de evaluación](#8-casos-de-evaluación) | Este proyecto | `evals/cases.jsonl` |

---

## 1. Corpus YAML

Seis archivos en `data/canonical/`. Son la **fuente de verdad** del agente y una
proyección **pública** del perfil maestro privado; la derivación es sustractiva
([DEC-003](ARQUITECTURA.md#dec-003--la-frontera-de-privacidad-es-el-corpus-no-el-prompt)).

**Campos comunes a los seis archivos:**

```yaml
source_id: master.md#professional-experience   # de qué sección del maestro deriva
updated_at: 2026-09-11                         # fecha de la última derivación
```

`source_id` no es decorativo: es lo que permite auditar una afirmación del agente hasta
la sección del documento maestro de la que salió.

### `profile.yaml`

Datos canónicos de identidad, resúmenes por enfoque de rol, fortalezas e idiomas.
**Campos deliberadamente ausentes**, no filtrados aguas abajo sino nunca presentes:
teléfono, circunstancias de salida de Cicada, compensación, historial de reclutadores y
el proceso de Banorte.

### `education.yaml`

```yaml
education:
  - id: unam-mac
    institution: UNAM — FES Acatlán
    degree_es: …            # el par es/en existe donde el CV es bilingüe
    degree_en: …
    years: "2019 – 2023"
    gpa: "9.39/10"
    status_es: …            # "título en trámite" viaja con el registro, no en una nota aparte
    foundation: [ … ]
```

### `experience.yaml`

```yaml
experience:
  - id: cicada
    organization: Cicada
    role_es / role_en: …
    start_date: "2024-01"   # ISO parcial, no texto libre
    end_date: "2026-05"
    domain: …
    technologies: [ … ]
    technical_notes: [ … ]  # matices que el agente puede decir si le preguntan
    highlights:
      - id: nats_price_feed
        proficiency: PROVEN            # el nivel viaja con el logro, no sólo con la habilidad
        domains: [backend, data, finance]
        es: >-
          …
        caveat: >-                     # opcional; si existe, se concatena al chunk
          …
```

`caveat` es el campo que impide que un logro se lea más fuerte de lo que fue. Se
concatena **dentro del mismo chunk** que la afirmación, no en metadatos: el modelo puede
no ver nada más que el texto recuperado.

### `projects.yaml`

```yaml
projects:
  - id: newman-eval-framework
    name: …
    attribution: own        # own | contribution | not_mine   ← el campo que importa
    proficiency: PROJECT
    domains: [ … ]
    period: "2026-08"
    context: …
```

`attribution` es la forma legible por máquina de las notas "no atribuírselo" del perfil
maestro:

| Valor | Significa | El agente debe decir |
|---|---|---|
| `own` | Lo construyó Adrián | Puede describirlo como suyo |
| `contribution` | Contribuyó código a un producto de terceros | "contribuye a", nunca "su producto" |
| `not_mine` | Lo construyó alguien más | Debe decirlo explícitamente |

### `skills.yaml`

Diez categorías, cada una con una lista de habilidades:

```yaml
categories:
  backend:
    label: Backend
    skills:
      - { name: FastAPI, proficiency: PROVEN, domains: [backend] }
      - { name: Django signals, proficiency: FAMILIAR, domains: [backend],
          note: "MATIZ: sólo a nivel de LECTURA. … NUNCA implementó ni diseñó una
                 signal. No presentarlo como que sabe usarlas." }
```

`proficiency` es uno de cinco valores, y su significado es normativo, no descriptivo:

| Nivel | Significa | Lenguaje permitido |
|---|---|---|
| `PROVEN` | Experiencia profesional en producción | "tiene experiencia profesional en" |
| `EXPERIENCED` | Conocimiento sólido de trabajo | "ha trabajado con", nunca "es experto en" |
| `FAMILIAR` | Exposición | "tiene familiaridad con" |
| `LEARNING` | Estudiando activamente | "lo está aprendiendo"; **nunca** "sabe" |
| `PROJECT` | Sólo proyecto personal o académico | "lo usó en un proyecto", nunca "en producción" |

El vocabulario completo, con las frases prohibidas por nivel, está en
[`POLITICAS.md`](POLITICAS.md#1-lenguaje-por-nivel-de-dominio) y vive como dato en
`policy.yaml`.

### `policy.yaml`

No contiene hechos sobre la trayectoria sino **reglas sobre cómo hablar de ellos**:
lenguaje por nivel, negaciones absolutas, negaciones de autoría, temas fuera de alcance
y reglas generales de respuesta. Se documenta en
[`POLITICAS.md`](POLITICAS.md), porque es una política y no un esquema de datos.

---

## 2. Manifiesto del corpus

```json
{
  "generated_at": "2026-09-12T05:09:35Z",
  "corpus_sha256": "a13f9815…",
  "file_count": 6,
  "files": {
    "education.yaml": { "sha256": "5481a7bd…", "bytes": 1480 }
  }
}
```

**Para qué sirve.** Un cambio al corpus es un cambio al comportamiento del agente tan
real como un cambio al código, pero es mucho menos visible en una revisión.
`tests/unit/test_corpus_manifest.py` compara el manifiesto contra el disco y **falla la
build** si divergen. Regenerar es explícito: `devbox run manifest`.

**El segundo uso, que resultó ser el importante:** `corpus_sha256` es lo que permite
decir contra **qué versión exacta de los datos** se tomó una medición. Sin eso, una
tabla de resultados en un documento es una afirmación sin fecha.

---

## 3. Modelo de chunk

Derivado, nunca editado a mano, reconstruible desde cero en cada arranque.

```python
@dataclass(frozen=True, slots=True)
class Chunk:
    id: str  # "skill:backend:Django" · "experience#cicada:nats_price_feed"
    text: str  # autocontenido: nombra su propio sujeto
    entity_type: str  # profile | education | experience | project | skill | skills | policy
    entity_id: str  # a qué registro del YAML corresponde
    source_id: str  # heredado del YAML: trazabilidad hasta el maestro
    context_prefix: str = ""  # se antepone SÓLO al embeber
    metadata: dict = {}

    @property
    def embedding_text(self) -> str:
        return f"{self.context_prefix}\n{self.text}" if self.context_prefix else self.text
```

**`context_prefix` es la pieza no obvia.** El texto que se embebe no es el texto que se
devuelve: el prefijo restaura el contexto que el troceado quitó (*"Cicada, ingeniero de
software, 2024-2026:"*) para que el vector caiga cerca de las preguntas correctas, pero
no se le muestra al modelo dos veces. Es la forma barata de *contextual retrieval*.

**Distribución actual** (159 chunks, corpus `a13f9815`, 2026-09-11):

| `entity_type` | Chunks | Granularidad |
|---|---:|---|
| `skill` | 100 | uno por habilidad individual |
| `experience` | 24 | uno por logro |
| `skills` | 10 | uno por categoría de habilidad |
| `project` | 9 | uno por proyecto |
| `profile` | 8 | titular, resúmenes, fortalezas, idiomas |
| `policy` | 5 | uno por tema fuera de alcance |
| `education` | 3 | uno por bloque educativo |

Las dos granularidades de habilidad conviven a propósito: la de categoría responde
"¿qué sabe de IA?", la individual responde "¿sabe Kubernetes?". La segunda existe porque
la primera falló de forma medible
([DEC-011](ARQUITECTURA.md#dec-011--errores-propios-encontrados-por-las-pruebas)).

---

## 4. Open Responses

**Impuesto por la plataforma.** Es el único contrato que no se puede negociar, y el
único cuya especificación tiene una suite ejecutable
([DEC-015](ARQUITECTURA.md#dec-015--correr-la-especificación-ejecutable-no-mi-lectura-de-ella)).

### Petición

```
POST {base}/responses
Authorization: Bearer <clave>
Content-Type: application/json
```

```python
class ResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")  # ← no es descuido

    model: str | None
    input: str | list[dict]  # cadena suelta O arreglo de items
    instructions: str | None
    tools: list[dict] | None
    tool_choice: Any
    stream: bool = False
    store: bool = False
    previous_response_id: str | None
    temperature: float | None
    max_output_tokens: int | None
```

**`extra="allow"` es una decisión, no una omisión.** El formulario de registro deja al
operador adjuntar parámetros arbitrarios —su propio ejemplo es
`{"temperature": 0.7, "reasoning": {"effort": "medium"}}`—. Rechazar campos desconocidos
convertiría una configuración inocua del operador en un 422.

**`input` acepta cuatro formas** y las cuatro circulan: cadena suelta; arreglo de items
con `content` como cadena; con `content` como lista de partes tipadas
(`input_text`/`output_text`/`text`); y mezclas de las anteriores. `parse_transcript` las
normaliza todas a `list[Turn]`. Los items de tipo `function_call`, `function_call_output`
y `reasoning` que llegan en la entrada **se ignoran**: son nuestros para emitir, no del
cliente para dirigir.

*Permisivo al entrar, estricto al salir.*

### Respuesta

**Los 31 campos son todos requeridos.** El esquema no tiene una sola propiedad
opcional, cosa que la prosa de la especificación no deja ver y que costó 23 campos
faltantes en la primera corrida de conformidad.

```python
class ResponseObject(BaseModel):
    # identidad y estado
    id: str  # "resp_<hex>"
    object: Literal["response"]
    created_at: int
    completed_at: int | None
    status: "queued|in_progress|completed|failed|incomplete"
    model: str
    output: list[OutputMessage | FunctionCallItem]

    # resultado
    error: ResponseError | None
    incomplete_details: IncompleteDetails | None
    usage: Usage | None
    metadata: dict

    # eco de la configuración de la petición
    instructions: str | None
    previous_response_id: str | None
    max_output_tokens: int | None
    max_tool_calls: int | None
    prompt_cache_key: str | None
    safety_identifier: str | None
    reasoning: dict | None
    text: TextField
    tools: list[dict]
    tool_choice: str = "auto"
    truncation: "auto|disabled" = "disabled"
    parallel_tool_calls: bool = True
    store: bool = False
    background: bool = False
    service_tier: str = "default"
    temperature: float = 1.0
    top_p: float = 1.0
    top_logprobs: int = 0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
```

Un agente de CV no tiene uso para `top_logprobs` ni `frequency_penalty`. Una respuesta
conforme los lleva de todos modos, haciendo eco de lo que estuvo en efecto en el turno.

**Items de salida — dos formas:**

```jsonc
// mensaje del asistente
{ "type": "message", "id": "msg_…", "status": "completed", "role": "assistant",
  "content": [{ "type": "output_text", "text": "…", "annotations": [] }] }

// llamada a una herramienta que declaró el CLIENTE, y que el cliente debe ejecutar
{ "type": "function_call", "id": "fc_…", "call_id": "…",
  "name": "…", "arguments": "{\"…\":\"…\"}", "status": "completed" }
```

Las **cuatro herramientas del agente nunca aparecen aquí**: corren del lado del servidor
dentro del bucle y sólo su efecto sobre la respuesta es visible. `function_call` es
exclusivamente para herramientas que el llamante declaró en `tools`.

### Normalización de `tools` — el detalle que costó una prueba

El esquema de una herramienta en la **petición** y en la **respuesta** no son la misma
forma. La suite de conformidad declara una herramienta sin `strict`; devolver la
declaración del cliente tal cual falla con `tools.0.strict: Invalid input`.
`_normalize_tool()` rellena los campos que la respuesta exige:

```python
{"type": "function", "name": …, "description": …,
 "parameters": … or {"type": "object", "properties": {}},
 "strict": body.get("strict", False)}
```

### Secuencia de eventos SSE

Con `"stream": true`, `Content-Type: text/event-stream`. La respuesta se produce
completa y luego se renderiza como la secuencia documentada, en trozos de 24 caracteres:

```
response.created
response.in_progress
response.output_item.added
response.content_part.added
response.output_text.delta      ← repetido
response.output_text.done
response.content_part.done
response.output_item.done
response.completed
```

**La salvedad honesta:** los deltas son porciones reales de la respuesta real, pero no
son tokens conforme el modelo los produce. Un cliente ve texto progresivo; lo que no
obtiene es una latencia al primer token menor. Está anotado en el código que lo hace.

### Manejo de errores

Un fallo del agente devuelve `status: "failed"` con un objeto `error` — **no un 500**.
Una UI de chat puede renderizar lo primero. El detalle interno va al log, nunca al
cuerpo.

---

## 5. Tarjeta de agente A2A

`GET /.well-known/agent-card.json`, sin autenticación. Sigue **A2A v1.0**.

```jsonc
{
  "name": "Adrián Barradas — Agente de CV",
  "description": "…",
  "version": "1.0.0",
  "documentationUrl": "https://github.com/…",
  "provider": { "organization": "Adrián Barradas", "url": "https://<host>" },

  "supportedInterfaces": [
    { "url": "https://<host>/v1", "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0" }
  ],

  "capabilities": { "streaming": true, "pushNotifications": false, "extendedAgentCard": false },
  "defaultInputModes":  ["text/plain"],
  "defaultOutputModes": ["text/plain"],

  "securitySchemes": {
    "bearer": { "httpAuthSecurityScheme": { "scheme": "bearer", "description": "Clave de API del agente." } }
  },
  "securityRequirements": [{ "schemes": { "bearer": { "list": [] } } }],

  "skills": [ { "id": "perfil", "name": "…", "description": "…",
                "tags": ["cv","perfil"], "examples": ["…"] } ]
}
```

**`supportedInterfaces`, no `url`.** A2A v1.0 reemplazó el campo `url` de nivel superior
por este arreglo; la plataforma rechaza la forma antigua con *"falta name o
supportedInterfaces"*. Se declara **una sola** interfaz: listar JSONRPC sería afirmar
algo que el endpoint no honra.

Un script de humo que seguía leyendo `card["url"]` pasaba de forma vacía. Hoy lee
`supportedInterfaces[0].url`.

---

## 6. Herramientas

Cuatro, todas **lectura pura** sobre estructuras en memoria. Sin shell, sin escrituras,
sin SQL, sin sistema de archivos, sin red saliente. El modelo nunca ve una consulta ni
una ruta: nombra una herramienta tipada y el código de aplicación decide qué significa.

```python
@dataclass(frozen=True, slots=True)
class ToolResult:
    data: dict[str, Any]
    evidence_ids: tuple[str, ...] = ()  # separado de `data` a propósito
```

`evidence_ids` viaja aparte del payload para que una respuesta se pueda rastrear hasta
sus fuentes **sin parsear el contenido**.

### `get_profile`

```json
{ "type": "object", "properties": {} }
```
Sin parámetros. Perfil, idiomas, resúmenes por enfoque, fortalezas y educación.

### `search_experience`

```json
{ "type": "object",
  "properties": {
    "query":  { "type": "string",  "description": "La pregunta o los términos, en español." },
    "top_k":  { "type": "integer", "description": "Cuántos resultados devolver (1-8)." } },
  "required": ["query"] }
```
La herramienta principal. `top_k` está **acotado a 8 dentro de la herramienta**, no en
el prompt: un techo que el modelo puede pedir rebasar y no obtener.

### `get_project`

```json
{ "type": "object",
  "properties": { "project_id": { "type": "string", "enum": ["…ids reales…"] } },
  "required": ["project_id"] }
```
El `enum` se genera del corpus, así que un id inventado no llega al handler. Devuelve
**siempre** la autoría; la descripción de la herramienta se lo dice al modelo de forma
explícita: *"Consulta siempre la autoría antes de atribuirle un proyecto."*

### `list_skills`

```json
{ "type": "object",
  "properties": {
    "category": { "type": "string", "enum": ["…categorías reales…"] },
    "domain":   { "type": "string", "description": "por ejemplo ai, backend, data" } } }
```
**Siempre devuelve el nivel de dominio junto al nombre.** No hay forma de pedir una
lista de habilidades pelada. Ése es el mecanismo de
[DEC-004](ARQUITECTURA.md#dec-004--la-política-de-honestidad-es-un-dato-estructurado-no-prosa).

### Errores de herramienta

Ninguno aborta el turno:

| Situación | Respuesta |
|---|---|
| Nombre de herramienta inventado | `{"error":"herramienta_desconocida","herramientas_disponibles":[…]}` |
| Argumentos que no son JSON o no son objeto | `{"error":"argumentos_invalidos","detalle":"…"}` |

Un error recuperable devuelto al modelo cuesta una iteración; un turno abortado cuesta
la respuesta.

---

## 7. Entorno

`.env.example` **es el contrato**, no un ejemplo. Dos pruebas lo sostienen: una falla si
el archivo llega a llevar una credencial real, y otra falla si deja de documentar
exactamente lo que `Settings` lee.

| Variable | Por defecto | Qué significa vacío / notas |
|---|---|---|
| `ENVIRONMENT` | `development` | No cambia ninguna decisión de seguridad. A propósito |
| `AGENT_API_KEY` | *(vacío)* | **Vacío = rechaza todo**, en todos los entornos. Sin excepción |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Lo que la tarjeta A2A publica como su propia URL |
| `AGENT_NAME` | `Adrián Barradas — Agente de CV` | Nombre en la tarjeta |
| `LLM_PROVIDER` | `openai_compatible` | `anthropic` \| `openai_compatible` |
| `LLM_BASE_URL` | *(Google AI Studio)* | Ignorado cuando el proveedor es `anthropic`: el SDK sabe su endpoint |
| `LLM_API_KEY` | *(vacío)* | |
| `LLM_MODEL` | `gemini-3.5-flash` | En producción: `claude-sonnet-5` |
| `LLM_MAX_OUTPUT_TOKENS` | `2048` | Medido: el p95 real de salida cabe holgado; 1024 truncaba |
| `LLM_TEMPERATURE` | `0.2` | |
| `LLM_TIMEOUT_S` | `45` | |
| `LLM_CACHE_TTL` | `1h` | `5m` \| `1h`. Con tráfico espaciado, 5m cuesta **más** que no cachear |
| `LLM_EFFORT` | `low` | Vacío para modelos que rechazan `output_config` (Haiku devuelve 400) |
| `EMBEDDINGS_MODEL` | `…/paraphrase-multilingual-MiniLM-L12-v2` | |
| `EMBEDDINGS_DIM` | `384` | El embedder **se niega a arrancar** si el modelo no produce esta dimensión |
| `EMBEDDINGS_CACHE_DIR` | `.fastembed_cache` | |
| `EMBEDDINGS_THREADS` | `1` | Acota las arenas de memoria de onnxruntime. Subirlo causó OOM en 1 GB |
| `EMBEDDINGS_BATCH_SIZE` | `8` | Idem |
| `RETRIEVAL_MODE` | `context` | `context` \| `structured` \| `dense` \| `hybrid`. El default ganó la medición |
| `RETRIEVAL_TOP_K` | `6` | |
| `RETRIEVAL_CANDIDATES` | `20` | Candidatos por recuperador antes de fusionar |
| `MAX_TOOL_ITERATIONS` | `6` | Un bucle de herramientas sin techo es una factura sin techo |
| `RATE_LIMIT_PER_MINUTE` | `30` | **Configurado pero NO aplicado.** Ver P3 en [ARQUITECTURA](ARQUITECTURA.md#4-trabajo-pendiente-y-límites-conocidos) |

---

## 8. Casos de evaluación

`evals/cases.jsonl`, un objeto JSON por línea. **45 casos, 12 categorías**, escritos
antes que el sistema que los califica.

```jsonc
{
  "id": "prof-01",
  "question": "¿Cuál es su perfil profesional?",
  "category": "profile",
  "expected_evidence_ids": ["profile#headline", "profile#summaries"],
  "expected_answer_points": ["ingeniero de software", "fintech", "matemáticas aplicadas"],
  "must_abstain": false,
  "forbidden_claims": [],
  "risk_tag": "low"
}
```

| Campo | Qué califica |
|---|---|
| `expected_evidence_ids` | La **recuperación**: ¿llegó la evidencia necesaria al contexto? Ver [recall y MRR](EVALUACION.md#recuperación) |
| `expected_answer_points` | La **cobertura** de la respuesta. Es un **piso**: la coincidencia literal no reconoce una paráfrasis correcta |
| `must_abstain` | Si el caso exige abstención en vez de respuesta |
| `forbidden_claims` | Afirmaciones que **no deben aparecer**. Es la columna que importa |
| `risk_tag` | Cuánto duele fallar este caso |

**Por qué `forbidden_claims` y no sólo puntos esperados:** calificar sólo por lo que debe
aparecer deja pasar una falsedad dicha con las palabras correctas. Una respuesta puede
tocar los tres puntos esperados y además afirmar algo falso.

`tests/unit/test_eval_cases.py` valida la forma de cada caso: 51 aserciones que impiden
que un caso mal escrito se cuele y reporte un aprobado que nadie ganó.
