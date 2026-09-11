# Evaluación de respuestas

Generado por `uv run python -m scripts.eval_answers`. Modelo `claude-sonnet-5`, recuperación `hybrid`.

**Cómo leer esto.** La calificación es determinista: coincidencia de subcadenas,
sin modelo juez. `Sin falsedades` es la columna que importa — busca afirmaciones
falsas concretas y no da falsos positivos. `Cobertura` es un **piso**: la
coincidencia literal no reconoce una paráfrasis correcta, así que subestima.

**42/42 casos sin ninguna afirmación falsa.**

| Categoría | Casos | Sin falsedades | Cobertura (piso) |
|---|---:|---:|---:|
| adversarial | 3 | 3/3 | 1.00 |
| ambiguous | 2 | 2/2 | 0.50 |
| attribution | 3 | 3/3 | 0.61 |
| comparison | 3 | 3/3 | 0.69 |
| deep-project | 4 | 4/4 | 0.81 |
| experience | 4 | 4/4 | 0.75 |
| negative | 4 | 4/4 | 0.62 |
| out-of-scope | 1 | 1/1 | 1.00 |
| privacy | 5 | 5/5 | 1.00 |
| proficiency-honesty | 4 | 4/4 | 0.29 |
| profile | 4 | 4/4 | 0.58 |
| technical-exact | 5 | 5/5 | 1.00 |

Latencia: p50 4.0 s · máx 9.3 s · tokens totales 57,142

## Fallos

Ninguno.
