"""The evaluation set is an asset, so it gets the same treatment as code.

Written before the system it grades, on purpose: a test set authored after the fact
tends to encode what the system already does rather than what it should do.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

CASES = Path(__file__).resolve().parents[2] / "evals" / "cases.jsonl"

REQUIRED_FIELDS = {
    "id",
    "question",
    "category",
    "expected_evidence_ids",
    "expected_answer_points",
    "must_abstain",
    "forbidden_claims",
    "risk_tag",
}

# Categories exist to make failures diagnosable. A drop in one of them says
# something specific; a drop in an overall average says almost nothing.
EXPECTED_CATEGORIES = {
    "profile",
    "experience",
    "technical-exact",
    "deep-project",
    "comparison",
    "negative",
    "proficiency-honesty",
    "attribution",
    "ambiguous",
    "adversarial",
    "privacy",
    "out-of-scope",
}


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line]


def test_cases_file_parses() -> None:
    assert len(load_cases()) >= 25, "the set is too small to cover the failure modes"


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: str(c["id"]))
def test_case_is_well_formed(case: dict[str, Any]) -> None:
    missing = REQUIRED_FIELDS - set(case)
    assert not missing, f"{case.get('id')} is missing {sorted(missing)}"
    assert case["category"] in EXPECTED_CATEGORIES, f"unknown category {case['category']!r}"
    assert case["risk_tag"] in {"low", "medium", "high"}
    assert case["question"].strip(), "a case needs a question"
    assert isinstance(case["must_abstain"], bool)


def test_case_ids_are_unique() -> None:
    ids = [c["id"] for c in load_cases()]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"duplicate case ids: {sorted(duplicates)}"


def test_every_category_is_represented() -> None:
    """A category with no cases is a failure mode nobody is watching."""
    present = {c["category"] for c in load_cases()}
    assert present == EXPECTED_CATEGORIES, f"unrepresented: {sorted(EXPECTED_CATEGORIES - present)}"


def test_every_case_is_gradable() -> None:
    """A case with no expected points and no forbidden claims cannot pass or fail."""
    for case in load_cases():
        assert case["expected_answer_points"] or case["forbidden_claims"] or case["must_abstain"], (
            f"{case['id']} has no gradable criterion"
        )


def test_the_honesty_categories_carry_forbidden_claims() -> None:
    """These categories fail by *asserting* something, so they need negative checks.

    Grading them on expected points alone would let a confident falsehood pass as
    long as it also happened to mention the right words.
    """
    needs_negatives = {"negative", "proficiency-honesty", "attribution"}
    for case in load_cases():
        if case["category"] in needs_negatives:
            assert case["forbidden_claims"], (
                f"{case['id']} is a {case['category']} case with no forbidden_claims; "
                "it can only detect a missing truth, not an asserted falsehood"
            )


def test_privacy_cases_must_abstain() -> None:
    for case in load_cases():
        if case["category"] == "privacy":
            assert case["must_abstain"], f"{case['id']} is a privacy case that does not abstain"
