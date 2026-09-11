# Decisiones técnicas

Un registro de decisiones, no una lista de features. Cada entrada dice qué se decidió,
qué alternativas se consideraron, y —cuando existe— qué medición respalda la elección.
Las decisiones que resultaron equivocadas también están aquí, con la corrección.

---

## DEC-001 — Sin framework de orquestación (LangChain, LlamaIndex)

**Decisión:** no usar LangChain ni LlamaIndex. El agente, la recuperación y el
adaptador de proveedor son código propio.

**Razones:**

1. El reto evalúa explícitamente el criterio detrás de las decisiones técnicas. Un
   framework esconde justamente las capas que hay que defender: chunking, ensamblado
   de contexto, orquestación de herramientas.
2. El contrato público es Open Responses. Ningún framework lo emite; la traducción
   había que escribirla igual, así que el framework quedaba como una capa intermedia
   que también hay que explicar.
3. El corpus son 135 chunks. El valor de LangChain está en la intercambiabilidad a
   escala; aquí sólo aporta peso de dependencias y superficie de versiones.

**Costo aceptado:** más código propio que mantener. A este tamaño, unas 700 líneas.

**Cuándo revisaría esto:** si el sistema necesitara varios backends de vector store
intercambiables en caliente, o integraciones con muchas fuentes heterogéneas.

---

## DEC-002 — Índice en memoria, no PostgreSQL + pgvector

**Decisión:** el índice vive en memoria (matriz numpy de 135×384 y un BM25 propio).
No hay base de datos.

**Contexto:** el plan original contemplaba PostgreSQL con pgvector, tanto por la
familiaridad con Postgres como por la señal de arquitectura.

**Por qué cambió:** el corpus resultó ser 135 chunks de YAML estático que viajan
dentro del repositorio. Sobre eso:

- Un producto coseno exacto sobre 135×384 tarda ~4 ms. No hay problema de latencia
  que resolver.
- La búsqueda es exacta, no aproximada: no hay parámetros HNSW/IVFFlat que calibrar
  ni un acantilado de recall que descubrir en producción.
- Los datos no cambian entre despliegues. No hay escrituras, ni concurrencia, ni
  necesidad de que el índice sobreviva a un reinicio: se reconstruye en 5 segundos.

El propio reto advierte que estas piezas "no deben añadirse sólo para hacerla más
compleja". Una base de datos para guardar 135 filas que nunca cambian es exactamente
eso.

**Cómo queda reversible:** `Embedder` es un Protocol y el índice está detrás de
`RetrievalEngine`. Cambiar a pgvector es una clase nueva, no una reescritura.

**Cuándo revisaría esto:** cuando el corpus no quepa en memoria, cuando varios
procesos deban compartir el índice, o cuando haya escrituras en caliente.

---

## DEC-003 — La frontera de privacidad es el corpus, no el prompt

**Decisión:** los datos privados se excluyen en el origen. `data/canonical/` es una
proyección pública derivada a mano del perfil maestro privado, y la derivación es
sustractiva.

Quedan fuera: teléfono, las circunstancias en que terminó el empleo en Cicada,
cualquier dato de compensación, historial de reclutadores y evaluaciones, y el propio
proceso de Banorte.

**Razón:** un prompt que dice "no reveles el teléfono" es una instrucción que un
modelo puede ignorar y que una inyección puede intentar rodear. **El agente no puede
revelar lo que nunca ingirió.** El mensaje de rechazo que sí existe es una cortesía
hacia el usuario, no el control de seguridad.

**Cómo se verifica:** `tests/unit/test_corpus_privacy.py` falla la build si algún
patrón privado aparece en `data/`. Ya atrapó dos casos reales durante el desarrollo.

---

## DEC-004 — La política de honestidad es un dato estructurado, no prosa

**Decisión:** cada habilidad lleva su nivel de dominio (`PROVEN`, `EXPERIENCED`,
`FAMILIAR`, `LEARNING`, `PROJECT`) y cada proyecto lleva su autoría (`own`,
`contribution`, `not_mine`). La herramienta `list_skills` **siempre** devuelve el
nivel junto al nombre, y el texto recuperable de cada habilidad incluye ya la frase
honesta ("NO tiene experiencia profesional con esto").

**Razón:** este es el riesgo real de un agente de CV. Un modelo servicial, presionado
por un reclutador que dice "necesitamos Azure", tiende a suavizar un no hasta que
parece un sí. Si el modelo recibe un nombre de tecnología pelado, puede presentarlo
como experiencia. Si recibe `Kubernetes / EKS — nivel LEARNING. NO tiene experiencia
profesional con esto`, la afirmación falsa requiere contradecir la evidencia en vez de
simplemente rellenar un hueco.

Lo mismo con autoría: el bot de producción del Instituto Newman lo construyó otra
persona, y Don Chambas es una contribución a un producto ajeno. Atribuirse trabajo de
otros es peor que no saber algo.

**Cómo se verifica:** categorías dedicadas en `evals/cases.jsonl`
(`proficiency-honesty`, `attribution`, `negative`), cada una con `forbidden_claims`
además de puntos esperados —porque calificar sólo por lo que debe aparecer deja pasar
una falsedad dicha con las palabras correctas.

---

## DEC-005 — Contrato primero, calidad después

**Decisión:** el endpoint `/v1/responses` se construyó y se probó contra un agente
stub antes de que existiera recuperación alguna.

**Razón:** una recuperación perfecta detrás de un endpoint que no cumple el contrato
vale cero. El orden inverso es la forma habitual de descubrir un problema de
integración el último día.

**Consecuencia de diseño:** `app/openresponses/` es una frontera de traducción.
Nada en `app/agent/`, `app/retrieval/` o `app/tools/` importa desde ahí, y nada de ahí
sabe cómo se produce una respuesta. Las pruebas de transporte usan un agente falso, a
propósito: hacerlas depender de un LLM alcanzable sería justo el acoplamiento que la
frontera existe para evitar.

---

## DEC-006 — Sin estado de conversación

**Decisión:** el agente no persiste conversaciones. No hay tabla `response`, ni Redis,
ni `previous_response_id`.

**Evidencia:** el formulario de registro de la plataforma tiene un selector
"Estado de la conversación" cuya opción **por defecto** es *"Reproducir transcripción
(sin estado)"*. La plataforma reenvía la transcripción completa en cada turno; la
alternativa con `previous_response_id` es opt-in.

**Consecuencia:** se eliminó un subsistema entero del plan original. Lo único que el
agente decide es cuánta transcripción pagar: `MAX_HISTORY_TURNS = 12`.

---

## DEC-007 — Embeddings locales en ONNX

**Decisión:** `fastembed` con `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensiones,
~220 MB), en CPU, en el mismo contenedor.

**Alternativa considerada:** una API de embeddings alojada. Se descartó porque
introduce una tercera credencial, un salto de red en la ruta de lectura, y costo por
consulta.

**A favor del modelo local:**

- Determinismo. El mismo texto produce el mismo vector entre corridas, que es lo que
  hace que la evaluación de recuperación sea **reproducible** y no sólo repetible.
- Es el mismo encoder cuyos umbrales ya se habían calibrado sobre contenido en español
  en trabajo previo, así que la calibración se aprovecha en vez de empezar de cero.
- Cero costo por consulta, cero dependencia externa en la ruta caliente.

**Costo aceptado:** ~220 MB en la imagen y unos segundos de arranque en frío.

---

## DEC-008 — Recuperación híbrida, elegida por medición

**Decisión:** modo `hybrid` en producción: búsqueda densa y BM25 en paralelo, fusionadas
con Reciprocal Rank Fusion.

**Medición** (`docs/EVALUATION-RETRIEVAL.md`, 33 casos con evidencia esperada):

| Modo | Recall | MRR | p50 | p95 |
|---|---:|---:|---:|---:|
| `dense` | 0.818 | 0.745 | 5.5 ms | 10.3 ms |
| `hybrid` | **0.879** | 0.742 | 4.5 ms | 6.7 ms |

Los seis puntos de diferencia son exactamente los casos de término exacto que la
búsqueda densa falla: `ISIN`, `LocalStack`. El MRR queda empatado, lo que dice que
híbrido **encuentra más cosas** sin degradar el orden de lo que ya encontraba.

**Por qué RRF y no una mezcla de puntajes:** las similitudes coseno y las sumas BM25
viven en escalas distintas. Combinarlas requiere inventar una ponderación que a su vez
habría que calibrar. RRF descarta las magnitudes y fusiona rangos, así que sobrevive a
un cambio de encoder o de corpus sin re-ajuste.

**El reranker quedó diseñado y sin construir.** Con recall de 0.879 sobre 135 chunks,
el cuello de botella no es la precisión del top-k.

---

## DEC-009 — Adaptador de proveedor, y por qué valió la pena

**Decisión:** `LLMAdapter` es un Protocol con dos implementaciones: una compatible con
OpenAI (cubre Google AI Studio, Cerebras, Groq, OpenAI —difieren sólo en URL base,
modelo y clave) y una nativa de Anthropic.

Esta decisión se pagó sola durante el desarrollo. La secuencia real fue:

1. Se intentó **Cerebras**. La clave autenticaba pero la cuenta no tenía facturación:
   `payment_required`.
2. Se cambió a **Google AI Studio**. Funcionó, hasta descubrir que el tier gratuito
   permite **20 solicitudes por día por modelo** (`quotaId:
   GenerateRequestsPerDayPerProjectPerModel-FreeTier`). Suficiente para probar, no para
   evaluar ni para demostrar.
3. Se cambió a **Anthropic**, que no habla el formato OpenAI y necesitó una segunda
   implementación.

Los tres cambios no tocaron una línea por encima de `app/llm/`.

**Modelo:** `claude-sonnet-5`, con `effort: "low"`. Responder una pregunta apoyada en
evidencia recuperada no es una tarea de razonamiento difícil. El *thinking* se deja
encendido: apagarlo en los modelos actuales tiene sus propios modos de falla, incluido
que el modelo escriba una llamada a herramienta dentro del texto visible.

---

## DEC-010 — Tres defectos de integración que sólo aparecen llamando al proveedor

No son decisiones sino hallazgos, y los tres tienen la misma forma: el error se
manifiesta en el turno siguiente al que lo causa.

**1. `thought_signature` de Gemini.** Gemini 3 adjunta una firma opaca a cada llamada
a herramienta y **rechaza la petición siguiente** si no se devuelve
(`Function call is missing a thought_signature`). El adaptador la descartaba.

**2. Bloques de *thinking* de Anthropic.** El mismo problema con otro nombre: el turno
del asistente lleva bloques de pensamiento que deben volver intactos junto con los
resultados de herramienta.

Un solo mecanismo cubre ambos: `ChatMessage.provider_raw` y `ToolCall.provider_extra`.
El adaptador devuelve su propia representación del turno y el bucle la reproduce
verbatim sin interpretarla. El costo de que un tercer proveedor tenga su propia
exigencia es cero por encima de `app/llm/`.

**3. Errores del proveedor invisibles.** El adaptador lanzaba sólo el código de
estado. Un 400 causado por un esquema de herramienta mal formado era indiagnosticable.
Ahora se registra y se propaga el mensaje del proveedor —la clave viaja en un
encabezado, no en el cuerpo, así que el mensaje es seguro de mostrar; el cuerpo
completo y la petición no lo son.

---

## DEC-011 — Errores propios encontrados por las pruebas

Se registran porque la pregunta "¿cómo verificas que el agente responde de forma
confiable?" se contesta mejor con fallos reales atrapados que con una promesa.

**`ISIN` no recuperaba nada.** El corpus dice "ISINs" y la consulta decía "ISIN".
Justo el caso de término exacto para el que existe la búsqueda léxica, silenciosamente
roto. Se corrigió con plegado de plural simétrico, aplicado en indexación y en
consulta.

**"¿Ha trabajado con Kubernetes en producción?" recuperaba el bot de *producción* de
Newman.** La palabra incidental "producción" pesaba más que el único término que
importaba, porque los chunks de habilidades eran del tamaño de una categoría entera.
Se corrigió con un chunk por habilidad: cada tecnología tiene ahora su propia
afirmación recuperable con la frase honesta ya escrita.

**Una prueba mía afirmaba una propiedad que RRF no tiene.** Escribí que un documento
en rangos 2 y 2 debía ganarle a uno en rangos 1 y 3. El recíproco es convexo, así que
es al revés: la fusión premia una aparición fuerte, no la castiga. La propiedad que sí
se cumple —y que la prueba ahora verifica— es que aparecer en ambas listas le gana a
encabezar una sola.

**Los casos de privacidad estaban contaminando la métrica de recuperación.** Esperaban
evidencia `policy#out_of_scope`, pero los resuelve la compuerta de política **antes**
de que corra la recuperación, así que sólo podían puntuar cero. Contarlos reportaba
como fallo de recuperación un componente que funcionaba como se diseñó. Excluirlos
subió el recall de híbrido de 0.763 a 0.879: la cifra anterior era pesimista y
equivocada, no conservadora.

---

## DEC-012 — Tarjeta de agente A2A

**Decisión:** servir `/.well-known/agent-card.json`.

**Razón:** el formulario de registro acepta una URL de tarjeta y autocompleta el
formulario entero. Convierte el registro en un solo pegado y hace que el agente sea
*descubrible*, no sólo invocable. Costó unas 40 líneas.

---

## DEC-013 — Despliegue en Railway, y el archivo de configuración que ya no sirve

**Decisión:** un contenedor en Railway, en el workspace personal (no en el de la
empresa con la que colabora). Sin base de datos, sin volúmenes, sin trabajos cron.

El agente Guía confirmó que el despliegue es de **libre elección**: *"No hay una
plataforma, proveedor cloud, arquitectura ni tecnología específica definida como
requisito."* Railway se eligió porque es la plataforma que ya opera, el servicio no
tiene estado, y la latencia la domina el LLM y no el cómputo propio.

**El tropiezo, que vale la pena registrar porque cuesta una tarde:** el patrón
habitual es un `railway.toml` en la raíz del repositorio. Ese archivo **no se detecta
solo**. El primer despliegue construyó con los valores por defecto de la plataforma y
sin comando de arranque, y falló sin un mensaje que lo explicara: el contexto del
despliegue mostraba `builder: RAILPACK` y `startCommand: null`, ignorando por completo
el archivo.

Intentar apuntar el servicio al archivo por API devuelve, hoy, un rechazo directo:
*"Config as Code (railway.json / railway.toml) is deprecated. Use Infrastructure as
Code (.railway/railway.ts) instead."* El formato nuevo requiere el paquete npm
`@railway/config`, que no tiene sentido añadir a un proyecto de Python sólo para
declarar tres campos.

**Resolución:** el comando de build, el de arranque, el healthcheck y la política de
reinicio se fijan **directamente en el servicio**. `railway.toml` se conserva en el
repositorio como documentación legible de esa configuración, con una nota explícita de
que no es la fuente efectiva.

**Lo que se pierde:** la configuración deja de estar versionada junto al código. Es un
costo real y se acepta a conciencia; la alternativa era arrastrar `node_modules` a un
proyecto de Python. Si esto creciera a varios servicios, el balance se invierte y
migraría a Infrastructure as Code.

**Segundo tropiezo — la versión de Python.** El builder actual (Railpack) instala
Python vía mise y eligió **3.13.15**, contra un proyecto fijado a `>=3.12,<3.13`. La
build murió en el paso de dependencias con `No interpreter found for Python ==3.12.*`,
que es un mensaje claro pero llega envuelto en cientos de líneas de buildkit. La
corrección es un archivo `.python-version` con `3.12`: Railpack lo respeta, y de paso
`uv` lo usa en local y en CI, así que las tres cosas quedan fijadas por el mismo
archivo en vez de por tres configuraciones distintas.

**Build:** `uv sync --frozen --no-dev && uv run python -m scripts.warm_model`. El segundo
comando descarga los ~220 MB del modelo ONNX durante la construcción. Sin eso, la
primera petición tras un arranque en frío paga la descarga, y un fallo de red se
manifiesta como un timeout ante quien está evaluando el agente en vez de como una
build rota.


---

## Referencias

El diseño se apoya en trabajo publicado. Se listan porque una decisión defendida con
una fuente es más fácil de discutir —y de refutar— que una defendida con intuición.

- Lewis et al. (2020), *Retrieval-Augmented Generation for Knowledge-Intensive NLP
  Tasks* — la separación entre memoria paramétrica del modelo y memoria externa
  recuperada. <https://arxiv.org/abs/2005.11401>
- Liu et al. (2023), *Lost in the Middle: How Language Models Use Long Contexts* — por
  qué una ventana de contexto más grande no equivale a recuperación confiable, y por
  qué el modo `context` es una línea base a medir y no una solución.
  <https://arxiv.org/abs/2307.03172>
- Es et al. (2023), *RAGAS: Automated Evaluation of Retrieval Augmented Generation* —
  separar calidad de recuperación de calidad de respuesta.
  <https://arxiv.org/abs/2309.15217>
- Anthropic (2024), *Introducing Contextual Retrieval* — anteponer contexto al chunk
  antes de embeberlo, y la complementariedad entre recuperación densa y BM25.
  <https://www.anthropic.com/engineering/contextual-retrieval>
- Qdrant, *Hybrid Search* — fusión de rangos frente a mezcla de puntajes.
  <https://qdrant.tech/documentation/search/text-search/hybrid-search/>
- OWASP GenAI, *LLM Top 10 (2025)* — el marco de `docs/SECURITY.md`.
  <https://genai.owasp.org/llm-top-10/>
- NIST AI 600-1, *Generative Artificial Intelligence Profile* — información de alta
  integridad como aquella que puede verificarse y ligarse a evidencia; es el
  argumento conceptual detrás de los metadatos de procedencia.
  <https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf>
- Open Responses — especificación y pruebas de conformidad.
  <https://www.openresponses.org/>
