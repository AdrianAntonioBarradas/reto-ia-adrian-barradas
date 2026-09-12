# Pendientes

> Documento de trabajo, **no versionado**. Salió de responder las preguntas de
> `docs/ESTUDIO.md`: varias no eran dudas conceptuales sino huecos reales.

Nada de esto está implementado. Cada entrada trae lo necesario para retomarla sin volver
a investigar: **qué es**, **por qué importa**, **qué archivo se toca**, **cuánto cuesta**
y **la señal** que indica que ya toca hacerlo.

Orden: por valor, no por esfuerzo.

---

## Antes de la entrega

### P0 · Verificar saldo de la API key antes de la demo

**Qué:** confirmar que la cuenta de Anthropic tiene crédito.

**Por qué:** si se agota, el agente devuelve `status: "failed"` con un mensaje genérico,
**`/health` sigue devolviendo 200**, y no hay ninguna alerta. Ya pasó dos veces en este
proyecto: Cerebras (`payment_required`) y Google AI Studio (20 peticiones/día). En ambos
casos se descubrió llamando al endpoint.

**Estado a hoy:** quedan **$3.90** de saldo. Alcanza de sobra para la demo (37 ensayos
de 10 preguntas con caché caliente) pero **no para otra escalera completa con Sonnet**
($2.08) más la demo. Detalle en el presupuesto de P1.

**Costo:** dos minutos. **Es la única entrada de esta lista que es bloqueante.**

---

## Huecos con implicación real

### P1 · Observabilidad de tokens y costo — ✅ RESUELTO

> **Implementado.** El log ahora incluye `model`, `input_tokens`, `output_tokens` y
> `cache_read_tokens` por petición, y el adaptador contabiliza los tokens de caché que
> antes ignoraba — un error que subestimaba el input por un factor de ~970.
> Se descubrieron además dos defectos relacionados, también corregidos: nadie leía
> `finish_reason`, así que una respuesta truncada volvía como completa; y
> `LLM_MAX_OUTPUT_TOKENS` valía 1024 en local y 8192 en producción, de modo que todas
> las mediciones se tomaron en una configuración que producción no corría.

**Qué era:** el `usage` se calculaba y se devolvía en la respuesta, pero
**no se registraba en el log**. `app/api/responses.py` loguea turnos, modo de
recuperación, herramientas, evidencia y `short_circuited` — los tokens no.

**Por qué importa:** sin eso no se puede responder "¿cuánto cuesta operarlo?" sin entrar a
la consola del proveedor, y no hay forma de detectar que una petición se volvió cara. Es
también el prerrequisito de cualquier conversación sobre escalamiento: no puedes optimizar
lo que no mides.

**Dónde:** `app/api/responses.py`, el `logger.info("responses.completed", extra={...})`.

**Cómo:** agregar `input_tokens`, `output_tokens`, `total_tokens` y `model` al `extra`.
Con eso, `railway logs | grep responses.completed` ya permite sumar el gasto por día. El
paso siguiente —si algún día importa— sería un contador Prometheus en `/metrics`.

**Costo:** ~5 líneas.

**Señal de que urge:** ya. Es barato y responde una pregunta que te hiciste.

#### Costo real, medido

**Ya no es una estimación.** Con la contabilidad corregida (P1 implementado) y un dato
real de facturación, estos son los números.

**El dato duro:** la corrida completa de la escalera con Haiku —168 llamadas, 4 modos—
costó **$1.04 USD**. Sonnet es el doble de caro por token, así que la misma corrida con
Sonnet ronda **$2.08**.

**Lo que realmente domina el costo, y no es el output.** El prompt de sistema en modo
`context` son **17,443 tokens** (las cuatro capas de prompt más los 135 chunks). La
salida mediana son 304 tokens. El input pesa ~57× más que la salida.

Precios de caché de Anthropic: lectura = 0.1× del input base, escritura con TTL de 5 min
= 1.25×, con TTL de 1 hora = 2×.

**Costo por turno, modo `context`:**

| Modelo | Caché caliente | Caché fría (write) | Sin caché |
|---|---:|---:|---:|
| Sonnet 5 | **$0.0065** | $0.0466 | $0.0379 |
| Haiku 4.5 | $0.0033 | $0.0233 | $0.0190 |

#### El hallazgo incómodo: la caché puede estar costándote dinero

Una escritura de caché cuesta **1.25×** el input normal. Si el turno siguiente llega
después del TTL de 5 minutos, esa escritura nunca se aprovecha y **pagaste 25% de más**:

```
escritura de caché (5 min)  $0.0436   ← lo que pagas si nadie vuelve en 5 min
input sin caché             $0.0349   ← lo que habrías pagado sin caché
lectura de caché            $0.0035   ← 90% más barato, si llegas a tiempo
```

**La caché sólo empieza a ganar a partir del segundo turno dentro de la ventana.** Para
una demo donde el evaluador pregunta con pausas, el patrón más probable es *una
escritura por pregunta* — el peor caso posible.

**La corrección, si importa:** Anthropic ofrece TTL de **1 hora** con
`cache_control: {"type": "ephemeral", "ttl": "1h"}`. Cuesta 2× al escribir pero dura
una hora. Para una demo de 10 preguntas espaciadas:

| Estrategia | Costo de 10 preguntas espaciadas |
|---|---:|
| TTL 5 min (lo que hay hoy) | **$0.466** |
| TTL 1 hora | **$0.128** |
| Sin caché | $0.379 |

Es un cambio de una línea en `app/llm/anthropic_native.py` y **reduce el costo de una
demo espaciada a la cuarta parte**. Queda como pendiente P7.

#### Presupuesto: qué alcanza con $3.90

| Actividad | Costo | Cuántas veces |
|---|---:|---|
| Demo de 10 preguntas **seguidas** (caché caliente) | $0.105 | **37 demos** |
| Demo de 10 preguntas **espaciadas** (caché fría cada vez) | $0.466 | 8 sesiones |
| Evaluación de respuestas, 42 casos, un modo | ~$1.18 | 3 corridas |
| **Escalera completa con Sonnet** (168 llamadas) | **~$2.08** | **1 sola** |

**Conclusión operativa:** el saldo alcanza de sobra para la demo y para ensayarla varias
veces. **No alcanza para otra escalera completa con Sonnet más la demo.** Si vas a
volver a correr la escalera, hazlo con Haiku ($1.04) o mide un solo modo.

#### ¿Subir a 2048 encarece algo?

**No, prácticamente nada.** `max_tokens` es un **techo, no un objetivo**: el modelo genera
lo que necesita y se factura por lo generado, no por el límite. La salida mediana son 304
tokens y seguirá siéndolo.

Lo único que cambia es el caso raro que antes se truncaba a 1024 y ahora se completa —
unos cientos de tokens extra, del orden de $0.003. A cambio, desaparece el riesgo de
entregar una respuesta cortada a media frase en la demo, que era real: una llamada de
verificación produjo **795 tokens de salida**, por encima del máximo que había medido.

### P2 · OWASP 2026 — ✅ RESUELTO

> **Aplicado como complemento, no como reescritura.** `SECURITY.md` lleva ahora una
> sección de actualización con la tabla de migración 2025→2026, cada encabezado con su
> doble numeración, y la entrada de LLM07 reescrita como **LLM08:2026 Hidden Context
> Exposure** — incluida la implicación de que en modo `context` el corpus entero de
> 17,443 tokens es contexto oculto, y las tres mitigaciones de la edición mapeadas a lo
> que ya hace el proyecto.
>
> Al renumerar aparecieron **dos errores de la versión original**: la sección de
> envenenamiento de datos estaba etiquetada LLM03 cuando es LLM04:2025, y
> **la categoría de cadena de suministro faltaba por completo**. Ambos corregidos; la de
> suministro se escribió desde cero, con lo que no está cubierto dicho explícitamente.

**Qué era:** `docs/SECURITY.md` estaba estructurado sobre el OWASP GenAI LLM Top 10 **2025**. El
**2026** se publicó el 4 de agosto de 2026 (`~/Downloads/OWASP-GenAI-LLM-Top-10-2026-v1.0.pdf`).

**Qué cambió** — renumeración, más un re-scope importante:

| 2025 | 2026 | Movimiento |
|---|---|---|
| LLM01 Prompt Injection | LLM01 | igual |
| LLM02 Sensitive Information Disclosure | LLM02 | igual |
| LLM06 Excessive Agency | **LLM03** | ▲ sube |
| LLM03 Supply Chain | LLM04 | ▼ |
| LLM04 Data and Model Poisoning | LLM05 | ▼ |
| LLM10 Unbounded Consumption | **LLM06** | ▲ sube |
| LLM09 Misinformation | **LLM07** | ▲ sube |
| LLM07 System Prompt Leakage | **LLM08 Hidden Context Exposure** | **re-scope** |
| LLM08 Vector and Embedding Weaknesses | LLM09 | ▼ |
| LLM05 Improper Output Handling | LLM10 | ▼ |

**Lo importante no es la renumeración, es LLM08.** "System Prompt Leakage" se amplió a
"Hidden Context Exposure", que ahora cubre **todo** lo que va en el contexto del modelo sin
ser visible al usuario: el prompt de sistema, **el texto recuperado**, y **los esquemas de
las herramientas**.

**La implicación concreta para este proyecto:** en modo `context` —que es producción— **el
corpus entero de 135 chunks es contexto oculto**. Eso no es un problema: es exactamente la
razón por la que DEC-003 (curar el corpus quitando lo privado) era la decisión correcta, y
ahora hay un marco que lo nombra.

**Las tres mitigaciones de LLM08 son casi literalmente lo que ya se hace:**

| Mitigación OWASP 2026 | Qué hace este proyecto |
|---|---|
| *"Do not put sensitive data in hidden context"* | Los datos privados nunca entraron al corpus (DEC-003) |
| *"Use deterministic methods and guardrails… outside the model"* | La compuerta de política corre antes del LLM |
| *"Enforce authorization independently from the LLM"* | Bearer fail-closed en código, sin excepción por entorno |

También vale citar la carta de apertura, porque describe la postura del proyecto mejor que
yo: *"Stop trying to build a model that cannot be fooled. Build the system around it, so
that when the model is fooled — and it will be — nothing important breaks."*

**Cómo abordarlo:** como **complemento**, no reescritura. Agregar a `SECURITY.md` una
sección de mapeo 2025→2026 y ampliar la entrada de LLM07 a Hidden Context Exposure con la
observación del modo `context`. El análisis de fondo no cambia.

**Nota adicional:** existe un *OWASP Top 10 for Agentic Applications (ASI) 2026*, lista
separada. No aplica mucho aquí (este agente tiene agencia mínima a propósito) pero
mencionarlo demuestra que se conoce el panorama.

**Costo:** ~1 hora, sólo documentación.

**Señal:** antes de la demo si hay tiempo. Es defensa técnica barata: *"revisé el marco
que salió hace un mes y estas son las diferencias"* es una respuesta fuerte.

---

### P3 · Rate limiting por cliente

**Qué:** `RATE_LIMIT_PER_MINUTE=30` está en la configuración y **no se aplica**.

**Por qué:** hoy el único techo real es la cuota del proveedor. Un bucle accidental agota
el presupuesto sin que nada lo frene. Ya está documentado como pendiente en `SECURITY.md`;
aquí queda con plan.

**Cómo:** una dependencia de FastAPI junto a `require_api_key`, con un *token bucket* en
memoria por clave. Devolver **429** con `Retry-After`. Con una sola réplica basta; con
varias haría falta Redis (detalle en `ESTUDIO.md` §9).

**Costo:** ~30 líneas más pruebas.

**Señal:** cuando el endpoint reciba tráfico que no controles, o antes si quieres poder
decir que está aplicado en vez de configurado.

---

### P4 · Medir con un modelo más barato — ✅ RESUELTO

> **Medido.** Resultados completos en `docs/EVALUATION-MODELS.md`. Titular: la
> honestidad se sostiene en Haiku —vive en el corpus, no en el modelo— pero en los modos
> con herramientas gasta **4× más tokens**, lo que hace que un modelo a mitad de precio
> salga ~2× más caro por tarea. Se queda Sonnet por 5 puntos de cobertura.
> Efecto colateral: Haiku **rechaza** `output_config`, así que el parámetro tuvo que
> volverse opcional en el adaptador.

**Qué era:** todas las cifras eran de `claude-sonnet-5` con `effort: low`.

**Por qué importa:** "¿aguanta un modelo más barato?" es una pregunta razonable de un
evaluador, y hoy la respuesta honesta es "no lo medí". El arnés ya existe para
contestarla.

**Cómo:**
```bash
LLM_MODEL=claude-haiku-4-5 uv run python -m scripts.eval_answers --ladder --write
```

**Qué esperar** (hipótesis, no medición): las tareas son modestas —elegir entre cuatro
herramientas y redactar desde evidencia que ya trae la respuesta escrita— así que gran
parte debería aguantar. Donde esperaría degradación es en `comparison`, `ambiguous` y en
la resistencia a la **presión de encaje**.

**Costo:** una corrida, ~$0.30, unos 15 minutos.

**Señal:** si el costo por conversación llegara a importar, o si quieres poder responder
la pregunta con un número. **No afirmes nada sobre Haiku en la demo sin haberlo
corrido** — sería justo el error que este proyecto se pasó tres veces corrigiendo.

---

### P5 · El modo `context` carga el embedder sin necesitarlo

**Qué:** en modo `context` no hay recuperación, pero el manejador de *lifespan* construye
el índice igual, cargando la sesión ONNX: **~700 MB de RAM que no se usan**.

**Por qué:** es el factor que determina cuántas réplicas caben por máquina. Sin el
embedder, cada réplica bajaría a menos de 150 MB — un factor de casi 5 en densidad.

**Dónde:** `app/main.py` (lifespan) y `app/retrieval/engine.py::get_engine`, que ya sabe
que sólo `dense` y `hybrid` necesitan embedder. Falta que el lifespan no fuerce la
construcción cuando el modo no la requiere.

**Cuidado:** el modo `context` sí necesita los **chunks** (los concatena en el prompt); lo
que no necesita son los **vectores**. La separación es entre construir el corpus y
construir el índice denso.

**Costo:** ~15 líneas y una prueba.

**Señal:** cuando la densidad por máquina importe, o si quieres bajar el plan de Railway.

---

### P6 · Nadie ha medido si `MAX_HISTORY_TURNS = 12` es el número correcto

**Qué:** 12 es un valor elegido con criterio, no medido. El conjunto de evaluación son
**preguntas sueltas**: no hay casos multi-turno, así que la memoria conversacional no está
evaluada en absoluto.

**Por qué importa:** es un hueco de la evaluación, no sólo del parámetro. El agente podría
estar rompiéndose en la cuarta pregunta de seguimiento y ninguna métrica lo diría.

**Cómo:** agregar 5-8 casos multi-turno a `evals/cases.jsonl` (una conversación con
seguimientos que dependan del contexto previo) y correr con distintos valores.

**Costo:** medio día, contando escribir los casos.

**Señal:** si alguien reporta que el agente "olvida"; o antes, porque es el hueco de
cobertura más claro que tiene la evaluación hoy.

---

### P7 · TTL de caché de 1 hora — ✅ RESUELTO

> **Implementado y desplegado.** `LLM_CACHE_TTL=1h`, expuesto como variable porque el
> tradeoff se invierte con tráfico realmente aislado. Verificado de extremo a extremo:
> la primera llamada escribe 17,491 tokens y la segunda los lee.
> Efecto colateral: al desplegarlo, el smoke test falló y destapó que su comprobación
> de la tarjeta A2A leía `card["url"]`, campo que desapareció en la migración a v1.0 —
> llevaba pasando en vacío desde entonces.

**Qué era:** el prompt de sistema se cacheaba con el TTL por defecto de 5 minutos. Con uso
espaciado —como una demo— cada pregunta paga una escritura de caché al 1.25×, que es
**25% más caro que no cachear**.

**Por qué importa:** reduce el costo de una demo espaciada de $0.466 a $0.128, casi a la
cuarta parte. Y el patrón de uso real de este agente es exactamente ése: preguntas
sueltas con pausas, no ráfagas.

**Dónde:** `app/llm/anthropic_native.py`, el bloque `cache_control` del system.

```python
{"type": "text", "text": system,
 "cache_control": {"type": "ephemeral", "ttl": "1h"}}
```

**El matiz:** la escritura con TTL de 1 h cuesta 2× en vez de 1.25×. Sale a cuenta a
partir del segundo turno dentro de la hora, y sale mal si de verdad sólo haces una
pregunta aislada al día.

**Costo:** una línea, más verificar que `cache_read_tokens` sube en la segunda llamada.

**Señal:** antes de la demo, si el saldo es ajustado. Con $3.90 no es urgente, pero es la
optimización con mejor relación esfuerzo/ahorro que queda.

---

## Registrados, sin urgencia

| Pendiente | Cuándo lo haría |
|---|---|
| **Juez automático (LLM) para respuestas** | Cuando la coincidencia de subcadenas empiece a estorbar más de lo que ayuda. Requiere evaluar al juez primero |
| **Streaming real token a token** | Si las respuestas se alargan y el TTFT importe. Cuesta una variante en streaming de cada adaptador y del bucle |
| **Migración a pgvector** | Cuando el corpus no quepa en memoria o varios procesos deban compartir índice (`ESTUDIO.md` §6) |
| **Persistencia de conversación** | Si el cliente deja de reenviar la transcripción, o si hace falta auditoría (`ESTUDIO.md` §4) |
| **Compactación (`/responses/compact`)** | Si las conversaciones crecen hasta presionar la ventana |
| **Transporte WebSocket** | Si el servidor necesita iniciar mensajes |
| **Reranker** | Si el recall fuera alto y el MRR bajo, o si el corpus creciera a miles |
| **Small agents / multi-agente** | Si hubiera subtareas realmente independientes. Hoy no hay ni hipótesis que medir |
| **Alerta de saldo / errores del proveedor** | Junto con P1. Hoy un agente sin créditos se ve sano en `/health` |

---

## Nota de método

Vale la pena notar de dónde salió esta lista: **de escribir las respuestas**. P1 apareció
al intentar responder "¿cuántos tokens he gastado?" y descubrir que no había forma de
saberlo. P5 apareció al explicar cómo escalaría. P6 apareció al justificar por qué 12.

Es el mismo patrón que produjo los mejores hallazgos del proyecto: **intentar explicar
algo con precisión es una forma barata de encontrar dónde no se sostiene.**
