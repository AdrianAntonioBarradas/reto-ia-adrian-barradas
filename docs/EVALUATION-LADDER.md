# La escalera de recuperación, medida de extremo a extremo

Generado por `uv run python -m scripts.eval_answers --ladder`. Modelo `claude-sonnet-5`.

Cuatro modos, un solo pipeline, el mismo conjunto de 42 casos. La única variable
es el paso de recuperación. Esto responde la pregunta que la evaluación de
recuperación no puede: **¿la recuperación resuelve un problema real, o el perfil
completo en el prompt bastaba?** Con 135 chunks no es una pregunta retórica.

| Modo | Qué hace | Sin falsedades | Cobertura | p50 | Tokens |
|---|---|---:|---:|---:|---:|
| `context` | perfil completo en el prompt, sin herramientas | 42/42 | 0.76 | 2.8 s | 9,406 |
| `structured` | sólo herramientas deterministas | 42/42 | 0.54 | 4.1 s | 54,223 |
| `dense` | coseno sobre embeddings | 42/42 | 0.68 | 4.0 s | 54,576 |
| `hybrid` | denso + BM25 fusionados con RRF | 42/42 | 0.71 | 3.9 s | 62,086 |

## Sin falsedades, por categoría

| Categoría | `context` | `structured` | `dense` | `hybrid` |
|---|---|---|---|---|
| adversarial | 3/3 | 3/3 | 3/3 | 3/3 |
| ambiguous | 2/2 | 2/2 | 2/2 | 2/2 |
| attribution | 3/3 | 3/3 | 3/3 | 3/3 |
| comparison | 3/3 | 3/3 | 3/3 | 3/3 |
| deep-project | 4/4 | 4/4 | 4/4 | 4/4 |
| experience | 4/4 | 4/4 | 4/4 | 4/4 |
| negative | 4/4 | 4/4 | 4/4 | 4/4 |
| out-of-scope | 1/1 | 1/1 | 1/1 | 1/1 |
| privacy | 5/5 | 5/5 | 5/5 | 5/5 |
| proficiency-honesty | 4/4 | 4/4 | 4/4 | 4/4 |
| profile | 4/4 | 4/4 | 4/4 | 4/4 |
| technical-exact | 5/5 | 5/5 | 5/5 | 5/5 |

## Fallos por modo

**`context`** — 0 fallo(s)


**`structured`** — 0 fallo(s)


**`dense`** — 0 fallo(s)


**`hybrid`** — 0 fallo(s)


