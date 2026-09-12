# Arquitectura y decisiones

Este documento reúne tres cosas que antes vivían separadas y no se entendían por
separado: **cómo está construido el sistema**, **por qué está construido así** y **bajo
qué restricciones se decidió**. Las decisiones no se sostienen sin el diagrama, y varias
sólo tienen sentido a la luz del contrato de integración del reto.

Los esquemas concretos están en [`ESQUEMAS.md`](ESQUEMAS.md), las mediciones en
[`EVALUACION.md`](EVALUACION.md) y las políticas en [`POLITICAS.md`](POLITICAS.md).

**Cifras vigentes** (2026-09-11, corpus `a13f9815`):

| | |
|---|---|
| Chunks del corpus | **159** |
| Prompt de sistema en modo `context` | **22,912** tokens |
| Pruebas | **145** |
| Casos de evaluación | **45** |

> **Sobre las cifras de medición.** Las tablas de resultados de este repositorio se
> tomaron sobre una versión anterior del corpus (**135 chunks**, 42 casos) y **no se
> reescriben** como si fueran de hoy: cada bloque de resultados lleva la versión del
> corpus contra la que corrió. Actualizar el número sin volver a medir sería inventar un
> dato. Ver la nota de método en [`EVALUACION.md`](EVALUACION.md#versiones-y-fechado).

---

## 1. Vista general

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
    │    context     sin recuperación, perfil completo   ← producción │
    │    structured  sólo herramientas deterministas                  │
    │    dense       coseno sobre embeddings                          │
    │    hybrid      dense + BM25 → RRF                               │
    └─────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  app/knowledge/  ·  CORPUS                                      │
    │  data/canonical/*.yaml  →  159 chunks semánticos                │
    │  Los YAML son la fuente de verdad; los chunks son un índice     │
    │  derivado y se pueden borrar y reconstruir sin perder nada.     │
    └─────────────────────────────────────────────────────────────────┘
```

### Las tres separaciones que importan

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

### Flujo de una pregunta

Tomando *"¿Ha trabajado con Kubernetes en producción?"*, en el modo `hybrid` que hace
visible cada etapa (en producción, modo `context`, los pasos 4 y 5 se colapsan en un
prompt que ya trae todo):

1. **Transporte.** `parse_transcript` normaliza el `input` —cadena suelta o arreglo de
   items con partes de contenido— a una lista de turnos.
2. **Política.** No coincide con ningún patrón de rechazo ni de inyección. Pasa.
3. **Prompt.** Cuatro capas de markdown desde `agent/prompts/`, más las instrucciones
   del operador si el registro las incluyó, subordinadas a la política.
4. **Modelo.** Pide `search_experience("Kubernetes producción")`.
5. **Recuperación.** BM25 y coseno en paralelo (~4 ms), fusión RRF. El primer resultado
   es `skill:cloud_devops:Kubernetes / EKS`, cuyo texto ya dice *"nivel LEARNING. NO
   tiene experiencia profesional con esto"*.
6. **Respuesta.** El modelo responde que no, que lo está aprendiendo.
7. **Telemetría.** Se registra la categoría, los IDs de evidencia, las herramientas
   llamadas, el modelo, los tokens y la latencia. **Nunca el contenido de la
   conversación.**

### Chunking

Escrito a mano, no un divisor por ventanas de tokens, porque el chunking cambia la
calidad de recuperación de forma medible:

- **Unidades semánticas:** un logro, un proyecto, una habilidad, un bloque educativo.
- **Texto autocontenido:** cada chunk nombra su propio sujeto. `"Redujo la carga
  operativa"` es inútil recuperado solo; `"Cicada — Ingeniero de Software: automatizó
  procesos de liquidación… redujo la carga operativa"` responde por sí mismo. Una
  prueba verifica que ningún chunk empiece con un pronombre suelto.
- **Prefijo de contexto antes de embeber:** la forma barata de *contextual retrieval*.
- **Dos granularidades para habilidades:** una por categoría (para "¿qué sabe de IA?")
  y una por habilidad individual (para "¿sabe Kubernetes?"). La segunda existe porque
  la primera falló de forma medible; ver [DEC-011](#dec-011--errores-propios-encontrados-por-las-pruebas).
- **El matiz viaja con la afirmación.** Un logro `FAMILIAR` lleva su `MATIZ IMPORTANTE`
  dentro del mismo chunk, y un proyecto lleva su autoría en el cuerpo del texto, no
  sólo en metadatos: el modelo puede no ver nada más.

Distribución actual (159 chunks): 100 por habilidad individual · 24 de experiencia ·
10 por categoría de habilidad · 9 de proyecto · 8 de perfil · 5 de política ·
3 de educación. El modelo de datos de un chunk está en
[`ESQUEMAS.md`](ESQUEMAS.md#3-modelo-de-chunk).

### Operación

| Aspecto | Cómo está resuelto |
|---|---|
| Salud | `GET /health` hace ping profundo y responde **503**, no 200 con bandera, para que un despliegue roto no se promueva |
| Migraciones | N/A — no hay base de datos ([DEC-002](#dec-002--índice-en-memoria-no-postgresql--pgvector)) |
| Secretos | Variables de entorno; `.env.example` es el contrato y una prueba falla si lleva un valor real |
| Reintentos | 429 y 5xx con backoff y jitter, respetando `Retry-After` |
| Techos | 6 iteraciones de herramienta, 12 turnos de historia, tokens de salida acotados, timeout por petición |
| Trazabilidad | IDs de evidencia y recuperadores usados en cada respuesta y en los logs |
| Fallo | Un error del agente devuelve un objeto `failed`, no un 500: una UI de chat puede renderizar el primero |
| Caché de prompt | TTL de 1 hora. El de 5 minutos costaba **más** que no cachear para tráfico espaciado: la escritura cuesta 1.25× y sólo se amortiza si hay una lectura dentro de la ventana |

---

## 2. Decisiones

Un registro de decisiones, no una lista de features. Cada entrada dice qué se decidió,
qué alternativas se consideraron, y —cuando existe— qué medición respalda la elección.
Las decisiones que resultaron equivocadas también están aquí, con la corrección.

### DEC-001 — Sin framework de orquestación (LangChain, LlamaIndex)

**Decisión:** no usar LangChain ni LlamaIndex. El agente, la recuperación y el
adaptador de proveedor son código propio.

**Razones:**

1. El reto evalúa explícitamente el criterio detrás de las decisiones técnicas. Un
   framework esconde justamente las capas que hay que defender: chunking, ensamblado
   de contexto, orquestación de herramientas.
2. El contrato público es Open Responses. Ningún framework lo emite; la traducción
   había que escribirla igual, así que el framework quedaba como una capa intermedia
   que también hay que explicar.
3. El corpus son unos cientos de chunks. El valor de LangChain está en la
   intercambiabilidad a escala; aquí sólo aporta peso de dependencias y superficie de
   versiones.

**Costo aceptado:** más código propio que mantener. A este tamaño, unas 700 líneas.

**Cuándo revisaría esto:** si el sistema necesitara varios backends de vector store
intercambiables en caliente, o integraciones con muchas fuentes heterogéneas.

### DEC-002 — Índice en memoria, no PostgreSQL + pgvector

**Decisión:** el índice vive en memoria (una matriz numpy de N×384 y un BM25 propio).
No hay base de datos.

**Contexto:** el plan original contemplaba PostgreSQL con pgvector, tanto por la
familiaridad con Postgres como por la señal de arquitectura.

**Por qué cambió:** el corpus resultó ser unos cientos de chunks de YAML estático que
viajan dentro del repositorio. Sobre eso:

- Un producto coseno exacto tarda ~4 ms. No hay problema de latencia que resolver.
- La búsqueda es exacta, no aproximada: no hay parámetros HNSW/IVFFlat que calibrar
  ni un acantilado de recall que descubrir en producción.
- Los datos no cambian entre despliegues. No hay escrituras, ni concurrencia, ni
  necesidad de que el índice sobreviva a un reinicio: se reconstruye en 5 segundos.

El propio reto advierte que estas piezas "no deben añadirse sólo para hacerla más
compleja". Una base de datos para guardar unos cientos de filas que nunca cambian es
exactamente eso.

**Cómo queda reversible:** `Embedder` es un Protocol y el índice está detrás de
`RetrievalEngine`. Cambiar a pgvector es una clase nueva, no una reescritura.

**Cuándo revisaría esto:** cuando el corpus no quepa en memoria, cuando varios
procesos deban compartir el índice, o cuando haya escrituras en caliente.

### DEC-003 — La frontera de privacidad es el corpus, no el prompt

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

### DEC-004 — La política de honestidad es un dato estructurado, no prosa

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
además de puntos esperados. El vocabulario permitido y prohibido por nivel está en
[`POLITICAS.md`](POLITICAS.md#1-lenguaje-por-nivel-de-dominio).

### DEC-005 — Contrato primero, calidad después

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

### DEC-006 — Sin estado de conversación

**Decisión:** el agente no persiste conversaciones. No hay tabla `response`, ni Redis,
ni `previous_response_id`.

**Evidencia:** el formulario de registro de la plataforma tiene un selector
"Estado de la conversación" cuya opción **por defecto** es *"Reproducir transcripción
(sin estado)"*. La plataforma reenvía la transcripción completa en cada turno; la
alternativa con `previous_response_id` es opt-in. Ver el
[anexo de restricciones](#anexo--restricciones-del-reto).

**Consecuencia:** se eliminó un subsistema entero del plan original. Lo único que el
agente decide es cuánta transcripción pagar: `MAX_HISTORY_TURNS = 12`.

### DEC-007 — Embeddings locales en ONNX

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

**Costo aceptado:** ~220 MB en la imagen y unos segundos de arranque en frío. En un
contenedor de 1 GB fue necesario acotar las arenas de memoria de onnxruntime:
`EMBEDDINGS_THREADS=1` y `EMBEDDINGS_BATCH_SIZE=8`, más el calentamiento del modelo en
tiempo de build. Sin eso, el proceso moría por OOM al construir el índice.

### DEC-008 — Recuperación híbrida, elegida por medición

**Decisión:** cuando hay recuperación, el modo es `hybrid`: búsqueda densa y BM25 en
paralelo, fusionadas con Reciprocal Rank Fusion. (Producción no recupera; ver
[DEC-014](#dec-014--el-modo-de-producción-es-context-porque-eso-dice-la-medición).)

**Medición:** recall 0.879 frente a 0.818 de `dense`, mismo conjunto de casos. Tabla
completa y condiciones en [`EVALUACION.md`](EVALUACION.md#recuperación).

Los seis puntos de diferencia son exactamente los casos de término exacto que la
búsqueda densa falla: `ISIN`, `LocalStack`. El MRR queda empatado, lo que dice que
híbrido **encuentra más cosas** sin degradar el orden de lo que ya encontraba.

**Por qué RRF y no una mezcla de puntajes:** las similitudes coseno y las sumas BM25
viven en escalas distintas. Combinarlas requiere inventar una ponderación que a su vez
habría que calibrar. RRF descarta las magnitudes y fusiona rangos, así que sobrevive a
un cambio de encoder o de corpus sin re-ajuste.

**El reranker quedó diseñado y sin construir.** Con ese recall, el cuello de botella no
es la precisión del top-k.

### DEC-009 — Adaptador de proveedor, y por qué valió la pena

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
La comparación medida contra Haiku 4.5 está en
[`EVALUACION.md`](EVALUACION.md#comparación-de-modelos).

### DEC-010 — Tres defectos de integración que sólo aparecen llamando al proveedor

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

### DEC-011 — Errores propios encontrados por las pruebas

Se registran porque la pregunta "¿cómo verificas que el agente responde de forma
confiable?" se contesta mejor con fallos reales atrapados que con una promesa. **El
patrón que se repite: el instrumento de medición falló más veces que el sistema
medido.**

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

**El calificador era ciego a la negación.** Reportaba 31/42 cuando el resultado real
era 41/42: contaba como afirmación prohibida la frase *"no tiene experiencia con
Kubernetes"* porque la subcadena aparecía. Se corrigió con una ventana de negación de
60 caracteres recortada en el límite de oración, y con exigir que la afirmación
prohibida nombre a su sujeto. Detalle en
[`EVALUACION.md`](EVALUACION.md#cómo-califica-el-grader).

**La contabilidad de tokens subestimaba el input ~970×** al no sumar los tokens de
caché, y `finish_reason` no lo leía nadie, así que una respuesta truncada en
`max_tokens` se veía igual que una completa. Ambas cosas están corregidas; las tablas
de la comparación de modelos son previas a la corrección y lo declaran.

### DEC-012 — Tarjeta de agente A2A

**Decisión:** servir `/.well-known/agent-card.json`.

**Razón:** el formulario de registro acepta una URL de tarjeta y autocompleta el
formulario entero. Convierte el registro en un solo pegado y hace que el agente sea
*descubrible*, no sólo invocable. Costó unas 40 líneas.

**Detalle de versión:** la tarjeta sigue A2A v1.0, que reemplazó el campo `url` de
nivel superior por un arreglo `supportedInterfaces`. La plataforma rechaza la forma
antigua con *"falta name o supportedInterfaces"*. Un script de humo que seguía leyendo
`card["url"]` pasaba de forma vacía por esa misma razón. Esquema completo en
[`ESQUEMAS.md`](ESQUEMAS.md#5-tarjeta-de-agente-a2a).

### DEC-013 — Despliegue en Railway, y el archivo de configuración que ya no sirve

**Decisión:** un contenedor en Railway, en el workspace personal. Sin base de datos,
sin volúmenes, sin trabajos cron.

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

**Tercer tropiezo — memoria.** El contenedor de 1 GB moría por OOM al construir el
índice denso: onnxruntime reserva arenas de memoria por hilo. Se resolvió con
`EMBEDDINGS_THREADS=1`, `EMBEDDINGS_BATCH_SIZE=8` y calentar el modelo en el build.

**Build:** `uv sync --frozen --no-dev && uv run python -m scripts.warm_model`. El segundo
comando descarga los ~220 MB del modelo ONNX durante la construcción. Sin eso, la
primera petición tras un arranque en frío paga la descarga, y un fallo de red se
manifiesta como un timeout ante quien está evaluando el agente en vez de como una
build rota.

### DEC-014 — El modo de producción es `context`, porque eso dice la medición

**Decisión:** `RETRIEVAL_MODE=context` por defecto. El perfil curado completo va en el
prompt; no hay recuperación en la ruta de producción.

**Medición:** cuatro modos × 42 casos, la recuperación como única variable. La línea
base gana en **todos** los ejes medidos: mejor cobertura, menor latencia y una sexta
parte de los tokens. Los cuatro modos son igual de honestos. Tabla completa y
condiciones en [`EVALUACION.md`](EVALUACION.md#la-escalera-de-recuperación).

**Por qué gana.** Con un corpus de este tamaño el perfil entero cabe holgadamente en el
prompt (22,912 tokens hoy), así que recuperar sólo puede quitar contexto que el modelo
habría usado. Además los modos con herramientas gastan varias llamadas por turno —cada
una reenviando el prompt de sistema y los esquemas de herramientas—, lo que explica el
factor 6 en tokens.

**Por qué el trabajo de recuperación no fue en balde:**

1. La pregunta "¿hace falta RAG aquí?" ahora tiene una respuesta con números en vez de
   una intuición. Ésa es la respuesta que el reto pide.
2. Deja de ganar en cuanto el corpus no quepa en un prompt, y volver es una variable
   de entorno.
3. La escalera detectó fallos reales de contenido —`ISIN`, Kubernetes— que
   contaminaban igual al modo `context`, porque los chunks son la misma fuente.

**Lo que se pierde al elegir `context`:** la respuesta ya no trae IDs de evidencia
recuperada, así que la trazabilidad es más débil. Es el costo real de esta decisión y
sería la razón para revertirla antes que cualquier otra.

> Enviar el modo que mis propios datos dicen que es peor habría vuelto decorativa la
> medición. El punto de medir es dejar que el resultado decida.

### DEC-015 — Correr la especificación ejecutable, no mi lectura de ella

**Qué pasó:** el tester oficial de Open Responses, corrido contra el endpoint
desplegado, dio **1 de 17**. En ese momento `tests/api/` tenía doce pruebas de
contrato y todas pasaban.

**Por qué no sirvieron de nada:** la misma lectura incompleta de la especificación
escribió las pruebas y la implementación. Una prueba escrita desde tu propia lectura
sólo puede confirmar esa lectura, nunca contradecirla. Faltaban **23 de los 31 campos
requeridos** del objeto de respuesta —el esquema no tiene propiedades opcionales, cosa
que la prosa no deja ver.

**Progresión:** 1/10 → 6/10 (campos requeridos) → 7/10 (SSE) → **8/10** (herramientas
del cliente y normalización de `tools`). Detalle en
[`EVALUACION.md`](EVALUACION.md#conformidad-con-open-responses).

**La lección operativa**, y es la que me llevo: cuando existe una especificación
ejecutable, correrla es lo primero, no lo último. Estuvo disponible todo el tiempo.

---

## 3. Lo que no se construyó, a propósito

- **Base de datos.** [DEC-002](#dec-002--índice-en-memoria-no-postgresql--pgvector).
- **Estado de conversación.** [DEC-006](#dec-006--sin-estado-de-conversación): la
  plataforma reenvía la transcripción.
- **Reranker.** Diseñado como etapa opcional; con el recall medido no es el cuello de
  botella.
- **Front end propio.** Sería una segunda superficie que nadie va a usar, con la clave
  de API expuesta en el navegador o un proxy extra que mantener. La interfaz de chat de
  la propia plataforma es la superficie de mayor fidelidad y funciona en un teléfono.
- **Compactación (`/responses/compact`) y transporte WebSocket.** Ver
  [`EVALUACION.md`](EVALUACION.md#lo-que-queda-fuera-y-por-qué).

**Sobre streaming, una corrección:** una versión anterior de este documento lo listaba
aquí como no construido. **Sí está implementado** y la prueba de conformidad SSE pasa.
Lo que no hace es emitir tokens conforme el modelo los produce: el adaptador devuelve
el turno completo y `app/openresponses/stream.py` lo trocea en deltas reales. Un
cliente ve texto progresivo; lo que no obtiene es una latencia al primer token menor.

---

## 4. Trabajo pendiente y límites conocidos

Un inventario que sólo lista victorias no es creíble. Esto es lo que falta, con la
señal que indicaría que ya toca hacerlo.

| # | Pendiente | Por qué importa | Señal para hacerlo |
|---|---|---|---|
| **P0** | **Verificar saldo del proveedor antes de la demo** | Si se agota, el agente devuelve `failed` con un mensaje genérico y **`/health` sigue en 200**. Ya pasó dos veces: Cerebras (`payment_required`) y Google AI Studio (20 req/día) | **Bloqueante.** Antes de cada demo |
| P3 | **Rate limiting por cliente** | `RATE_LIMIT_PER_MINUTE` está configurado y **no se aplica**. Hoy el único techo real es la cuota del proveedor; un bucle accidental agota el presupuesto sin que nada lo frene. ~30 líneas: token bucket en memoria junto a `require_api_key`, 429 con `Retry-After` | Cuando el endpoint reciba tráfico no controlado |
| P5 | **El modo `context` carga el embedder sin necesitarlo** | ~700 MB de RAM que no se usan; sin el embedder cada réplica bajaría de 150 MB, casi 5× en densidad. El modo `context` sí necesita los **chunks**, no los **vectores** | Cuando la densidad por máquina importe |
| P6 | **`MAX_HISTORY_TURNS = 12` no está medido** | Es un hueco de la **evaluación**, no sólo del parámetro: los 45 casos son preguntas sueltas, así que la memoria conversacional no está evaluada en absoluto. El agente podría romperse en la cuarta pregunta de seguimiento y ninguna métrica lo diría | Es el hueco de cobertura más claro que tiene la evaluación hoy |
| — | **Re-medir la recuperación sobre el corpus actual** | Cuesta **$0** y corre en segundos (`scripts/eval_retrieval.py`, sin LLM). No se hizo al curar estos documentos para no mezclar cifras de dos versiones del corpus | Es la primera que conviene actualizar si el corpus se mueve otra vez |

Registrados sin urgencia: juez automático para respuestas (requiere evaluar al juez
primero), streaming real token a token, migración a pgvector, persistencia de
conversación, compactación, transporte WebSocket, reranker, alerta de saldo.
**Small agents / multi-agente** queda descartado por ahora: no hay subtareas realmente
independientes, así que no hay ni hipótesis que medir.

> **De dónde salió esta lista:** de escribir las respuestas. La observabilidad de
> tokens apareció al intentar responder "¿cuántos tokens he gastado?" y descubrir que no
> había forma de saberlo; P5 al explicar cómo escalaría; P6 al justificar por qué 12.
> **Intentar explicar algo con precisión es una forma barata de encontrar dónde no se
> sostiene.**

---

## Anexo — Restricciones del reto

Fuente: agente **Guía del reto** y el formulario **Agentes → Añadir un agente** de la
plataforma del Reto IA Banorte, consultados el 2026-09-11. Las respuestas del agente
Guía son citas; el formulario es evidencia directa del contrato de integración y pesa
más que la conversación.

### El contrato de integración

| Campo | Valor / nota |
|---|---|
| Importar desde tarjeta de agente | `https://<host>/.well-known/agent-card.json` — autocompleta el formulario, incluida la URL base. **Opcional.** |
| Nombre | Requerido. |
| **URL base** | Requerido. *"Requests go to `{base URL}/responses`"*. Ejemplo: `https://my-agent.example.com/v1`. |
| **Clave de API** | Opcional. *"Se envía como `Authorization: Bearer …` y se almacena cifrada."* |
| Modelo | Opcional. |
| **Estado de la conversación** | Por defecto: **"Reproducir transcripción (sin estado)"**. Alternativa: `previous_response_id`. |
| Entrega de archivos | Por defecto "URL de capacidad". |
| Instrucciones | Instrucciones de sistema opcionales enviadas con cada solicitud. |
| Prompt suggestions | Hasta 8, una por línea. |
| Extra request parameters (JSON) | Ejemplo: `{"temperature": 0.7, "reasoning": {"effort": "medium"}}`. |
| Entrada de imágenes / archivos | Toggles, desactivados por defecto. |

**Consecuencias de diseño:** la ruta es `POST /v1/responses` registrando la base como
`https://<host>/v1`; autenticación Bearer validada *fail-closed*; modo sin estado por
defecto ([DEC-006](#dec-006--sin-estado-de-conversación)); la tarjeta A2A es barata y
de alto valor ([DEC-012](#dec-012--tarjeta-de-agente-a2a)); y el agente debe tolerar
`instructions` y parámetros extra en el cuerpo sin romperse —de ahí `extra="allow"` en
el modelo de petición.

### Lo que el agente Guía confirmó

- **Despliegue: opción libre.** *"No hay una plataforma, proveedor cloud, arquitectura
  ni tecnología específica definida como requisito."* Lo que importa es poder justificar
  la elección y sus trade-offs.
- **SSE no es obligatorio.** *"No está especificado que SSE sea obligatorio, ni se
  define una versión concreta de Open Responses que debas implementar."* Recomendación
  explícita: *"Implementa primero el camino no-streaming."* (Se implementó de todos
  modos, y la prueba de conformidad correspondiente pasa.)
- **No hay entregable diferenciado por seniority.** El nivel se refleja en la
  profundidad y el criterio de las decisiones técnicas.
- **Cómo se prueba el agente:** que responda de forma natural y consistente sobre el
  CV, que mantenga contexto en preguntas de seguimiento, que explique proyectos y
  habilidades **sin inventar información**, que la solución se pueda construir,
  integrar, desplegar y operar de verdad, y que las decisiones estén justificadas.
- **Casos de prueba que recomienda:** preguntas generales, específicas de proyecto,
  comparaciones, seguimientos con contexto, y **temas fuera del perfil para comprobar
  honestidad y límites**. Esa recomendación es la que estructura las 12 categorías de
  [`EVALUACION.md`](EVALUACION.md#las-12-categorías).

### Lo que NO está especificado

El agente Guía respondió explícitamente "no está especificado" a: rúbrica formal de
evaluación, **fecha límite**, **formato y duración de la demostración**, casos de prueba
concretos, versión concreta de Open Responses, y requisitos del material de entrega.
No se inventan ni se asumen.

> **Pendiente para Adrián:** confirmar fecha límite y formato de demo por el canal
> oficial de reclutamiento, no por el agente Guía.

### Dato de contexto

El propio agente Guía está desplegado en **Azure Container Apps**. Es una referencia de
que esperan un contenedor con un endpoint HTTP público, no un requisito de plataforma.

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
- OWASP GenAI, *LLM Top 10* — el marco de [`POLITICAS.md`](POLITICAS.md).
  <https://genai.owasp.org/llm-top-10/>
- NIST AI 600-1, *Generative Artificial Intelligence Profile* — información de alta
  integridad como aquella que puede verificarse y ligarse a evidencia; es el argumento
  conceptual detrás de los metadatos de procedencia.
  <https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf>
- Open Responses — especificación y pruebas de conformidad.
  <https://www.openresponses.org/>
