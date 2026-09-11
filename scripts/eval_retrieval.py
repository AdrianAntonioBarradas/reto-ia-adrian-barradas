"""Measure the retrieval ladder. No LLM, no tokens, no network.

Retrieval quality and answer quality are different failures with different fixes, so
they get different harnesses. This one answers a single question — *was the evidence
the answer needs actually retrieved?* — across all four rungs, on the same case set.

A perfect model cannot answer from evidence that was never fetched, so a low score
here caps everything downstream. Running it costs nothing, which means it can gate
CI in a way an LLM-backed evaluation never can.

    uv run python -m scripts.eval_retrieval
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import RetrievalMode
from app.knowledge.corpus import load_corpus
from app.retrieval.engine import RetrievalEngine

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "cases.jsonl"
REPORT_PATH = ROOT / "docs" / "EVALUATION-RETRIEVAL.md"

# Rungs that actually retrieve. "context" feeds the whole corpus to the model and
# "structured" uses deterministic lookups, so neither has a ranking to score —
# including them here would report a meaningless zero.
RANKED_MODES: tuple[RetrievalMode, ...] = ("dense", "hybrid")

DEFAULT_K = 6


@dataclass(frozen=True, slots=True)
class CaseScore:
    case_id: str
    category: str
    risk: str
    expected: tuple[str, ...]
    retrieved: tuple[str, ...]
    latency_ms: float
    must_abstain: bool = False

    @property
    def is_scorable(self) -> bool:
        """Whether this case measures *retrieval*.

        Two kinds of case are excluded, and getting this wrong understates the
        system badly. Cases with no expected evidence obviously have nothing to
        score. Less obviously, abstention cases — compensation, contact details, why
        a job ended — are answered by the policy gate *before* retrieval runs, so
        they can only ever score zero here. Counting them would report a retrieval
        failure for a component working exactly as designed.
        """
        return bool(self.expected) and not self.must_abstain

    @property
    def hits(self) -> int:
        return sum(1 for e in self.expected if self._matched(e))

    @property
    def recall(self) -> float:
        return self.hits / len(self.expected) if self.expected else 0.0

    @property
    def reciprocal_rank(self) -> float:
        for rank, source in enumerate(self.retrieved, start=1):
            if any(self._same(source, e) for e in self.expected):
                return 1.0 / rank
        return 0.0

    def _matched(self, expected: str) -> bool:
        return any(self._same(source, expected) for source in self.retrieved)

    @staticmethod
    def _same(source_id: str, expected: str) -> bool:
        """Prefix match, so a case can name a whole entity or one exact field.

        "experience#cicada" should be satisfied by "experience#cicada.compliance_
        screening": the case author cared about the role, not the bullet.
        """
        return source_id == expected or source_id.startswith(expected)


def load_cases() -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line
    ]


def score_mode(mode: RetrievalMode, cases: list[dict[str, Any]], top_k: int) -> list[CaseScore]:
    from app.config import get_settings
    from app.embeddings.local_onnx import LocalOnnxEmbedder

    embedder = LocalOnnxEmbedder(get_settings().embeddings_model)
    engine = RetrievalEngine(load_corpus(), embedder, mode=mode, top_k=top_k)

    scores: list[CaseScore] = []
    for case in cases:
        started = time.perf_counter()
        results = engine.search(case["question"], top_k=top_k)
        elapsed = (time.perf_counter() - started) * 1000
        scores.append(
            CaseScore(
                case_id=case["id"],
                category=case["category"],
                risk=case["risk_tag"],
                expected=tuple(case["expected_evidence_ids"]),
                retrieved=tuple(r.source_id for r in results),
                latency_ms=elapsed,
                must_abstain=bool(case.get("must_abstain")),
            )
        )
    return scores


def summarise(scores: list[CaseScore]) -> dict[str, float]:
    scorable = [s for s in scores if s.is_scorable]
    latencies = [s.latency_ms for s in scores]
    return {
        "cases": len(scorable),
        "recall": statistics.mean(s.recall for s in scorable) if scorable else 0.0,
        "any_hit": (sum(1 for s in scorable if s.hits) / len(scorable) if scorable else 0.0),
        "mrr": statistics.mean(s.reciprocal_rank for s in scorable) if scorable else 0.0,
        "p50_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_ms": (
            statistics.quantiles(latencies, n=20)[-1] if len(latencies) > 1 else latencies[0]
        ),
    }


def by_category(scores: list[CaseScore]) -> dict[str, float]:
    grouped: dict[str, list[CaseScore]] = {}
    for score in scores:
        if score.is_scorable:
            grouped.setdefault(score.category, []).append(score)
    return {c: statistics.mean(s.recall for s in group) for c, group in sorted(grouped.items())}


def render(results: Mapping[str, list[CaseScore]], top_k: int) -> str:
    lines = [
        "# Evaluación de recuperación",
        "",
        "Generado por `uv run python -m scripts.eval_retrieval`. Sin LLM: mide únicamente",
        "si la evidencia necesaria llega al contexto, que es el techo de todo lo demás.",
        "",
        f"`top_k = {top_k}`. Quedan fuera de estas cifras los casos de abstención",
        "(privacidad, adversariales): los resuelve la compuerta de política **antes** de",
        "que corra la recuperación, así que puntuarlos aquí reportaría como fallo de",
        "recuperación un componente que funciona como se diseñó. Se miden por separado.",
        "",
        "## Resumen por modo",
        "",
        "| Modo | Casos | Recall | Al menos 1 acierto | MRR | p50 | p95 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, scores in results.items():
        s = summarise(scores)
        lines.append(
            f"| `{mode}` | {int(s['cases'])} | {s['recall']:.3f} | {s['any_hit']:.3f} | "
            f"{s['mrr']:.3f} | {s['p50_ms']:.1f} ms | {s['p95_ms']:.1f} ms |"
        )

    lines += [
        "",
        "## Recall por categoría",
        "",
        "| Categoría | " + " | ".join(f"`{m}`" for m in results) + " |",
    ]
    lines.append("|---" * (len(results) + 1) + "|")
    categories = sorted({c for scores in results.values() for c in by_category(scores)})
    per_mode = {mode: by_category(scores) for mode, scores in results.items()}
    for category in categories:
        row = " | ".join(f"{per_mode[m].get(category, 0.0):.2f}" for m in results)
        lines.append(f"| {category} | {row} |")

    lines += ["", "## Casos sin ningún acierto", ""]
    any_miss = False
    for mode, scores in results.items():
        misses = [s for s in scores if s.is_scorable and not s.hits]
        if not misses:
            continue
        any_miss = True
        lines.append(f"**`{mode}`**")
        lines.append("")
        for miss in misses:
            lines.append(f"- `{miss.case_id}` ({miss.category}) — esperaba {list(miss.expected)}")
        lines.append("")
    if not any_miss:
        lines.append("Ninguno.")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=DEFAULT_K)
    parser.add_argument("--write", action="store_true", help="write docs/EVALUATION-RETRIEVAL.md")
    args = parser.parse_args()

    cases = load_cases()
    results: dict[str, list[CaseScore]] = {
        mode: score_mode(mode, cases, args.top_k) for mode in RANKED_MODES
    }

    for mode, scores in results.items():
        s = summarise(scores)
        print(
            f"{mode:8s} recall={s['recall']:.3f} any_hit={s['any_hit']:.3f} "
            f"mrr={s['mrr']:.3f} p50={s['p50_ms']:.1f}ms p95={s['p95_ms']:.1f}ms "
            f"(n={int(s['cases'])})"
        )

    report = render(results, args.top_k)
    if args.write:
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(f"\nwrote {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
