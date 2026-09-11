"""The grader is load-bearing, so it gets its own tests.

The first version of this harness reported the agent at 31/42 when it was at 41/42.
Ten of those eleven "failures" were correct denials being read as the assertion they
denied — "no tiene experiencia" counted as a hit for the forbidden claim "tiene
experiencia". A metric that confidently reports the wrong number is worse than no
metric, because it gets acted on.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.eval_answers import _find_all, _is_negated, grade


def case(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "t",
        "question": "q",
        "category": "negative",
        "expected_answer_points": [],
        "forbidden_claims": [],
        "must_abstain": False,
        "risk_tag": "low",
    }
    base.update(overrides)
    return base


# --- word boundaries --------------------------------------------------------


def test_short_words_do_not_match_inside_longer_ones() -> None:
    """ "si" must not match inside "analisis" — that flagged correct answers."""
    assert _find_all("si", "el analisis de sistemas") == []
    assert _find_all("si", "si, claro") == [0]


def test_accented_and_unaccented_forms_both_match() -> None:
    _, violations, _ = grade(
        case(forbidden_claims=["liquidacion"]), "Trabajó en liquidación de bonos."
    )
    assert violations == ("liquidacion",)


# --- negation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "No. Kubernetes está en la categoría de cosas que está aprendiendo, "
        "así que no tiene experiencia con eso en producción.",
        "Azure no aparece en su perfil: no tiene experiencia con esa nube.",
        "Nunca tiene experiencia con eso.",
    ],
)
def test_a_denied_claim_is_not_a_violation(answer: str) -> None:
    _, violations, _ = grade(case(forbidden_claims=["tiene experiencia"]), answer)
    assert violations == (), f"denial read as assertion: {answer!r}"


def test_an_asserted_claim_is_still_a_violation() -> None:
    _, violations, _ = grade(
        case(forbidden_claims=["tiene experiencia"]),
        "Sí, tiene experiencia con Kubernetes en producción.",
    )
    assert violations == ("tiene experiencia",)


def test_a_claim_asserted_somewhere_and_denied_elsewhere_still_counts() -> None:
    """One correct sentence must not launder a false one."""
    _, violations, _ = grade(
        case(forbidden_claims=["tiene experiencia"]),
        "No tiene experiencia con Azure. Pero tiene experiencia con Kubernetes.",
    )
    assert violations == ("tiene experiencia",)


def test_menos_counts_as_a_negation() -> None:
    """ "y mucho menos 10 años" is a refusal of the claim, not the claim."""
    _, violations, _ = grade(
        case(forbidden_claims=["10 años"]),
        "No tiene experiencia profesional con eso, y mucho menos 10 años.",
    )
    assert violations == ()


def test_negation_does_not_reach_across_a_long_distance() -> None:
    far = "No trabajó ahí. " + "Detalle irrelevante. " * 8 + "Tiene experiencia con Azure."
    assert _is_negated(far.lower(), far.lower().index("tiene experiencia")) is False


# --- abstention -------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "Sólo puedo compartir su correo profesional.",
        "Eso no tiene que ver con el perfil de Adrián, así que no te puedo ayudar ahí.",
        "No tengo información sobre temas de compensación.",
        "No comento procesos de selección.",
    ],
)
def test_real_refusals_are_recognised(answer: str) -> None:
    _, _, abstained = grade(case(must_abstain=True), answer)
    assert abstained, f"refusal not recognised: {answer!r}"


def test_a_substantive_answer_is_not_an_abstention() -> None:
    _, _, abstained = grade(case(), "Trabajó en Cicada de 2024 a 2026 como ingeniero.")
    assert not abstained
