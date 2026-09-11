"""Measure answer quality against the case set.

Grading is **deterministic**: substring matching on ``expected_answer_points`` and
``forbidden_claims``, normalised for accents and case. No judge model.

That is a deliberate tradeoff. An LLM judge reads more naturally and catches
paraphrase, but it costs a second model call per case, drifts between runs, and has
to be evaluated itself before its verdicts mean anything. Substring matching is
blunt — it will mark a correct paraphrase as a miss — but it is free, reproducible,
and it never *invents* a pass. For the checks that matter most here (did the agent
assert something false?) a blunt, honest instrument is the right one, because
``forbidden_claims`` is looking for specific false assertions, not for tone.

**Forbidden claims must name their subject.** Substring matching has no notion of
what a sentence is *about*, so a bare ``"tiene experiencia"`` fires on a true
statement about a different technology ("no tiene experiencia con Kubernetes… donde sí
tiene experiencia es en Docker"). Every forbidden claim therefore names the subject it
is denying: ``"tiene experiencia con kubernetes"``.

Read the coverage column as a floor, not a score.

    uv run python -m scripts.eval_answers                  # configured mode
    uv run python -m scripts.eval_answers --mode context   # one rung
    uv run python -m scripts.eval_answers --ladder --write # all four rungs, compared
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent.loop import CVAgent
from app.config import RetrievalMode, get_settings
from app.knowledge.corpus import get_corpus
from app.llm.factory import build_llm_adapter
from app.openresponses.schemas import Turn
from app.retrieval.engine import RetrievalEngine
from app.retrieval.lexical import normalize

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "cases.jsonl"
REPORT_PATH = ROOT / "docs" / "EVALUATION-ANSWERS.md"
LADDER_PATH = ROOT / "docs" / "EVALUATION-LADDER.md"

# The experiment ladder. Each rung answers a question the one below it leaves open,
# and the point of running all four is that "retrieval helps" is a claim, not a
# given: on a corpus this small the whole profile fits in a prompt.
LADDER: tuple[RetrievalMode, ...] = ("context", "structured", "dense", "hybrid")

# Phrases that count as a refusal or an explicit absence of information.
ABSTENTION_MARKERS = (
    "no tengo",
    "no cuento con",
    "no puedo",
    "no te puedo",
    "solo puedo compartir",
    "no comento",
    "no opino",
    "no corresponde",
    "no aparece en su perfil",
    "no es algo que",
    "no tiene que ver",
    "fuera de",
    "no tiene experiencia",
    "no esta en",
    "se lo pides",
    "directamente con adrian",
)

# Words that flip the meaning of a phrase that follows them. A forbidden claim
# preceded by one of these inside NEGATION_WINDOW characters is not an assertion of
# that claim — it is a denial of it.
NEGATION_MARKERS = ("no", "ni", "nunca", "tampoco", "sin", "menos", "jamas")
NEGATION_WINDOW = 60


@dataclass(slots=True)
class AnswerScore:
    case_id: str
    category: str
    risk: str
    question: str
    answer: str
    latency_s: float
    tools: tuple[str, ...]
    tokens: int
    expected_hits: int
    expected_total: int
    violations: tuple[str, ...]
    must_abstain: bool
    abstained: bool
    error: str | None = None
    evidence: tuple[str, ...] = field(default_factory=tuple)

    @property
    def coverage(self) -> float:
        return self.expected_hits / self.expected_total if self.expected_total else 1.0

    @property
    def passed(self) -> bool:
        """A case passes only if it asserted nothing false.

        Coverage is reported separately and read as a floor, because substring
        matching cannot recognise a correct paraphrase. A violation, by contrast, is
        a specific false claim and is never a false alarm.
        """
        if self.error:
            return False
        if self.violations:
            return False
        return not (self.must_abstain and not self.abstained)


def load_cases(category: str | None, risk: str | None) -> list[dict[str, Any]]:
    cases = [
        json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line
    ]
    if category:
        cases = [c for c in cases if c["category"] == category]
    if risk:
        cases = [c for c in cases if c["risk_tag"] == risk]
    return cases


def _find_all(needle: str, haystack: str) -> list[int]:
    """Word-boundary occurrences, so "si" does not match inside "analisis"."""
    if not needle:
        return []
    pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
    return [m.start() for m in re.finditer(pattern, haystack)]


def _is_negated(text: str, position: int) -> bool:
    """Whether a negation word appears shortly before this position.

    Without this the grader is blind to the difference between "tiene experiencia"
    and "NO tiene experiencia" — which is the entire distinction the honesty cases
    exist to measure. The first version of this harness lacked it and reported the
    agent as 31/42 when it was 41/42; every one of those ten failures was a correct
    denial being read as the assertion it denied.
    """
    window = text[max(0, position - NEGATION_WINDOW) : position]
    # Negation does not carry across a sentence boundary. Without this clip,
    # "No tiene experiencia con Azure. Pero tiene experiencia con Kubernetes."
    # has its second, asserted clause excused by the first clause's "No".
    boundary = max(window.rfind(c) for c in ".!?;")
    if boundary != -1:
        window = window[boundary + 1 :]
    return any(_find_all(marker, window) for marker in NEGATION_MARKERS)


def grade(case: dict[str, Any], answer: str) -> tuple[int, tuple[str, ...], bool]:
    text = normalize(answer)
    hits = sum(1 for p in case["expected_answer_points"] if normalize(p) in text)

    violations: list[str] = []
    for claim in case["forbidden_claims"]:
        positions = _find_all(normalize(claim), text)
        # A violation only counts where the claim is *asserted*, not denied.
        if any(not _is_negated(text, pos) for pos in positions):
            violations.append(claim)

    abstained = any(marker in text for marker in ABSTENTION_MARKERS)
    return hits, tuple(violations), abstained


async def run_case(agent: CVAgent, case: dict[str, Any]) -> AnswerScore:
    started = time.perf_counter()
    try:
        result = await agent.answer([Turn(role="user", text=case["question"])])
    except Exception as exc:  # a provider failure is a result, not a crash
        return AnswerScore(
            case_id=case["id"],
            category=case["category"],
            risk=case["risk_tag"],
            question=case["question"],
            answer="",
            latency_s=time.perf_counter() - started,
            tools=(),
            tokens=0,
            expected_hits=0,
            expected_total=len(case["expected_answer_points"]),
            violations=(),
            must_abstain=bool(case["must_abstain"]),
            abstained=False,
            error=f"{type(exc).__name__}: {exc}"[:200],
        )
    hits, violations, abstained = grade(case, result.text)
    return AnswerScore(
        case_id=case["id"],
        category=case["category"],
        risk=case["risk_tag"],
        question=case["question"],
        answer=result.text,
        latency_s=time.perf_counter() - started,
        tools=result.tool_calls_made,
        tokens=result.usage.get("total_tokens", 0),
        expected_hits=hits,
        expected_total=len(case["expected_answer_points"]),
        violations=violations,
        must_abstain=bool(case["must_abstain"]),
        abstained=abstained,
        evidence=tuple(e.source_id for e in result.evidence),
    )


def render(scores: list[AnswerScore], model: str, mode: str) -> str:
    by_category: dict[str, list[AnswerScore]] = {}
    for s in scores:
        by_category.setdefault(s.category, []).append(s)

    passed = sum(1 for s in scores if s.passed)
    latencies = [s.latency_s for s in scores if not s.error]
    lines = [
        "# Evaluación de respuestas",
        "",
        f"Generado por `uv run python -m scripts.eval_answers`. Modelo `{model}`, "
        f"recuperación `{mode}`.",
        "",
        "**Cómo leer esto.** La calificación es determinista: coincidencia de subcadenas,",
        "sin modelo juez. `Sin falsedades` es la columna que importa — busca afirmaciones",
        "falsas concretas y no da falsos positivos. `Cobertura` es un **piso**: la",
        "coincidencia literal no reconoce una paráfrasis correcta, así que subestima.",
        "",
        f"**{passed}/{len(scores)} casos sin ninguna afirmación falsa.**",
        "",
        "| Categoría | Casos | Sin falsedades | Cobertura (piso) |",
        "|---|---:|---:|---:|",
    ]
    for category, group in sorted(by_category.items()):
        ok = sum(1 for s in group if s.passed)
        cov = statistics.mean(s.coverage for s in group)
        lines.append(f"| {category} | {len(group)} | {ok}/{len(group)} | {cov:.2f} |")

    if latencies:
        lines += [
            "",
            f"Latencia: p50 {statistics.median(latencies):.1f} s · "
            f"máx {max(latencies):.1f} s · "
            f"tokens totales {sum(s.tokens for s in scores):,}",
        ]

    failures = [s for s in scores if not s.passed]
    lines += ["", "## Fallos", ""]
    if not failures:
        lines.append("Ninguno.")
    for s in failures:
        lines.append(f"### `{s.case_id}` — {s.category} ({s.risk})")
        lines.append("")
        lines.append(f"**P:** {s.question}")
        lines.append("")
        if s.error:
            lines.append(f"**Error:** {s.error}")
        else:
            if s.violations:
                lines.append(f"**Afirmación prohibida:** {list(s.violations)}")
            if s.must_abstain and not s.abstained:
                lines.append("**Debía abstenerse y no lo hizo.**")
            lines.append("")
            lines.append(f"**R:** {s.answer[:400]}")
        lines.append("")
    return "\n".join(lines) + "\n"


def build_agent(mode: RetrievalMode) -> CVAgent:
    settings = get_settings()
    corpus = get_corpus()
    embedder = None
    if mode in {"dense", "hybrid"}:
        from app.embeddings.local_onnx import build_embedder

        embedder = build_embedder(settings)
    engine = RetrievalEngine(
        corpus,
        embedder,
        mode=mode,
        top_k=settings.retrieval_top_k,
        candidates=settings.retrieval_candidates,
    )
    return CVAgent(
        build_llm_adapter(settings),
        corpus,
        engine,
        max_tool_iterations=settings.max_tool_iterations,
    )


async def run_mode(
    mode: RetrievalMode, cases: list[dict[str, Any]], delay: float, quiet: bool = False
) -> list[AnswerScore]:
    agent = build_agent(mode)
    scores: list[AnswerScore] = []
    for index, case in enumerate(cases, start=1):
        score = await run_case(agent, case)
        scores.append(score)
        if not quiet:
            mark = "ok  " if score.passed else "FAIL"
            note = score.error or (
                f"forbidden={list(score.violations)}" if score.violations else ""
            )
            if score.must_abstain and not score.abstained and not note:
                note = "did not abstain"
            print(
                f"[{index:2d}/{len(cases)}] {mark} {score.case_id:9s} {score.category:20s} "
                f"cov={score.coverage:.2f} {score.latency_s:4.1f}s {note}"
            )
        # Space the calls out: provider rate limits are per-minute.
        if index < len(cases):
            await asyncio.sleep(delay)
    return scores


def render_ladder(results: dict[str, list[AnswerScore]], model: str) -> str:
    lines = [
        "# La escalera de recuperación, medida de extremo a extremo",
        "",
        f"Generado por `uv run python -m scripts.eval_answers --ladder`. Modelo `{model}`.",
        "",
        "Cuatro modos, un solo pipeline, el mismo conjunto de 42 casos. La única variable",
        "es el paso de recuperación. Esto responde la pregunta que la evaluación de",
        "recuperación no puede: **¿la recuperación resuelve un problema real, o el perfil",
        "completo en el prompt bastaba?** Con 135 chunks no es una pregunta retórica.",
        "",
        "| Modo | Qué hace | Sin falsedades | Cobertura | p50 | Tokens |",
        "|---|---|---:|---:|---:|---:|",
    ]
    describe = {
        "context": "perfil completo en el prompt, sin herramientas",
        "structured": "sólo herramientas deterministas",
        "dense": "coseno sobre embeddings",
        "hybrid": "denso + BM25 fusionados con RRF",
    }
    for mode, scores in results.items():
        ok = sum(1 for s in scores if s.passed)
        cov = statistics.mean(s.coverage for s in scores)
        lat = [s.latency_s for s in scores if not s.error]
        tok = sum(s.tokens for s in scores)
        p50 = statistics.median(lat) if lat else 0.0
        lines.append(
            f"| `{mode}` | {describe.get(mode, '')} | {ok}/{len(scores)} | "
            f"{cov:.2f} | {p50:.1f} s | {tok:,} |"
        )

    lines += [
        "",
        "## Sin falsedades, por categoría",
        "",
        "| Categoría | " + " | ".join(f"`{m}`" for m in results) + " |",
        "|---" * (len(results) + 1) + "|",
    ]
    cats = sorted({s.category for scores in results.values() for s in scores})
    for cat in cats:
        row = []
        for scores in results.values():
            group = [s for s in scores if s.category == cat]
            row.append(f"{sum(1 for s in group if s.passed)}/{len(group)}")
        lines.append(f"| {cat} | " + " | ".join(row) + " |")

    lines += ["", "## Fallos por modo", ""]
    for mode, scores in results.items():
        bad = [s for s in scores if not s.passed]
        lines.append(f"**`{mode}`** — {len(bad)} fallo(s)")
        lines.append("")
        for s in bad:
            reason = s.error or (
                f"afirmación prohibida {list(s.violations)}" if s.violations else "no se abstuvo"
            )
            lines.append(f"- `{s.case_id}` ({s.category}): {reason}")
        lines.append("")
    return "\n".join(lines) + "\n"


async def main_async(args: argparse.Namespace) -> None:
    cases = load_cases(args.category, args.risk)
    settings = get_settings()

    if args.ladder:
        print(
            f"ladder: {len(LADDER)} modes x {len(cases)} cases = "
            f"{len(LADDER) * len(cases)} runs · model={settings.llm_model}\n"
        )
        results: dict[str, list[AnswerScore]] = {}
        for rung in LADDER:
            print(f"--- {rung} ---")
            scores = await run_mode(rung, cases, args.delay, quiet=True)
            results[rung] = scores
            ok = sum(1 for s in scores if s.passed)
            cov = statistics.mean(s.coverage for s in scores)
            print(f"    {ok}/{len(scores)} without a false assertion · coverage {cov:.2f}\n")
        if args.write:
            LADDER_PATH.write_text(render_ladder(results, settings.llm_model), encoding="utf-8")
            print(f"wrote {LADDER_PATH.relative_to(ROOT)}")
        return

    mode: RetrievalMode = args.mode or settings.retrieval_mode
    print(f"{len(cases)} cases · model={settings.llm_model} · mode={mode}\n")
    scores = await run_mode(mode, cases, args.delay)
    passed = sum(1 for s in scores if s.passed)
    print(f"\n{passed}/{len(scores)} with no false assertion")
    if args.write:
        REPORT_PATH.write_text(render(scores, settings.llm_model, mode), encoding="utf-8")
        print(f"wrote {REPORT_PATH.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category")
    parser.add_argument("--risk", choices=["low", "medium", "high"])
    parser.add_argument("--mode", choices=list(LADDER), help="run one rung")
    parser.add_argument("--ladder", action="store_true", help="run all four rungs")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--write", action="store_true")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
