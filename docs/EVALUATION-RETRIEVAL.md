# Evaluación de recuperación

Generado por `uv run python -m scripts.eval_retrieval`. Sin LLM: mide únicamente
si la evidencia necesaria llega al contexto, que es el techo de todo lo demás.

`top_k = 6`. Quedan fuera de estas cifras los casos de abstención
(privacidad, adversariales): los resuelve la compuerta de política **antes** de
que corra la recuperación, así que puntuarlos aquí reportaría como fallo de
recuperación un componente que funciona como se diseñó. Se miden por separado.

## Resumen por modo

| Modo | Casos | Recall | Al menos 1 acierto | MRR | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|
| `dense` | 33 | 0.818 | 0.879 | 0.745 | 5.5 ms | 10.3 ms |
| `hybrid` | 33 | 0.879 | 0.909 | 0.742 | 4.5 ms | 6.7 ms |

## Recall por categoría

| Categoría | `dense` | `hybrid` |
|---|---|---|
| adversarial | 1.00 | 1.00 |
| ambiguous | 0.00 | 0.00 |
| attribution | 1.00 | 1.00 |
| comparison | 0.83 | 0.83 |
| deep-project | 0.75 | 1.00 |
| experience | 0.88 | 0.88 |
| negative | 1.00 | 1.00 |
| proficiency-honesty | 1.00 | 1.00 |
| profile | 0.62 | 0.50 |
| technical-exact | 0.70 | 1.00 |

## Casos sin ningún acierto

**`dense`**

- `prof-04` (profile) — esperaba ['education#unam-mac']
- `tech-05` (technical-exact) — esperaba ['skills#domain_knowledge']
- `proj-04` (deep-project) — esperaba ['projects#localstack-lab']
- `amb-01` (ambiguous) — esperaba ['projects#newman-eval-framework', 'projects#llm-eval-harness']

**`hybrid`**

- `prof-01` (profile) — esperaba ['profile#headline', 'profile#summaries']
- `prof-04` (profile) — esperaba ['education#unam-mac']
- `amb-01` (ambiguous) — esperaba ['projects#newman-eval-framework', 'projects#llm-eval-harness']

