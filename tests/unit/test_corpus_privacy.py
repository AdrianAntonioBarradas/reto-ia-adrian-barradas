"""The privacy boundary is a property of the corpus, not of the prompt.

These tests fail the build if private information ever reaches ``data/``. That is
deliberate: an agent cannot disclose what was never ingested, so the check belongs
at the data layer where it is cheap and absolute, not at generation time where it
depends on the model behaving.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

CANONICAL = Path(__file__).resolve().parents[2] / "data" / "canonical"

# Patterns that must never appear anywhere in the public corpus. Each one is a
# concrete field from the private master profile that has no business here.
FORBIDDEN_PATTERNS: dict[str, str] = {
    "phone number": r"\+?52[\s\-]?\d{2,3}[\s\-]?\d{3}[\s\-]?\d{4}",
    "any 10-digit bare phone": r"(?<!\d)\d{10}(?!\d)",
    "dismissal / restructuring wording": (
        r"(?i)\b(despido|dismissal|restructuring|reestructura\w*)\b"
    ),
    "salary wording": r"(?i)\b(salario|sueldo|compensaci[oó]n esperada|salary|CTC)\b",
    "recruiter pipeline wording": (
        r"(?i)\b(reclutador\w*|recruiter|vacante en curso|HackerRank|Wonderlic)\b"
    ),
    "the Banorte process itself": r"(?i)\bBanorte\b",
}


# ``policy.yaml`` is the one file that must *name* the topics it refuses, so the
# topic-name patterns cannot apply to its ``out_of_scope`` section. Everything else
# in that file, and every other file, is scanned in full.
TOPIC_NAMING_PATTERNS = frozenset({"salary wording", "recruiter pipeline wording"})


def corpus_files() -> list[Path]:
    return sorted(CANONICAL.glob("*.yaml"))


def scannable_content(path: Path) -> tuple[str, frozenset[str]]:
    """Return the file's *data* as text, plus the patterns that apply to it.

    Comments are dropped on purpose: they document what was excluded, and naming an
    excluded field in a comment is not a leak. Only values that can reach the model
    are scanned.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    applicable = frozenset(FORBIDDEN_PATTERNS)
    if path.name == "policy.yaml":
        data = {k: v for k, v in data.items() if k != "out_of_scope"}
        applicable = applicable - TOPIC_NAMING_PATTERNS
    return yaml.safe_dump(data, allow_unicode=True), applicable


def test_corpus_is_not_empty() -> None:
    assert corpus_files(), "no canonical corpus files found"


@pytest.mark.parametrize("path", corpus_files(), ids=lambda p: p.name)
def test_corpus_file_is_valid_yaml(path: Path) -> None:
    assert yaml.safe_load(path.read_text(encoding="utf-8")) is not None


@pytest.mark.parametrize("path", corpus_files(), ids=lambda p: p.name)
def test_corpus_file_contains_no_private_data(path: Path) -> None:
    text, applicable = scannable_content(path)
    for label in applicable:
        match = re.search(FORBIDDEN_PATTERNS[label], text)
        assert match is None, (
            f"{path.name} contains {label}: {match.group(0)!r}. "
            "Private data must be excluded at the source, not filtered downstream."
        )


def test_policy_out_of_scope_still_refuses_compensation() -> None:
    """The exemption above must not become a hole: the refusal has to exist."""
    data = yaml.safe_load((CANONICAL / "policy.yaml").read_text(encoding="utf-8"))
    topics = " ".join(entry["topic"] for entry in data["out_of_scope"])
    assert "compensaci" in topics, "policy.yaml no longer refuses compensation questions"


def test_every_project_declares_attribution() -> None:
    """Credit for other people's work is the failure mode this guards against."""
    data = yaml.safe_load((CANONICAL / "projects.yaml").read_text(encoding="utf-8"))
    allowed = {"own", "contribution", "not_mine"}
    for project in data["projects"]:
        assert "attribution" in project, f"{project['id']} has no attribution field"
        assert project["attribution"] in allowed, (
            f"{project['id']} has attribution {project['attribution']!r}, expected one of {allowed}"
        )


def test_every_skill_declares_proficiency() -> None:
    """A skill without a tag could be presented as expertise. None may exist."""
    data = yaml.safe_load((CANONICAL / "skills.yaml").read_text(encoding="utf-8"))
    allowed = {"PROVEN", "EXPERIENCED", "FAMILIAR", "LEARNING", "PROJECT"}
    for category_name, category in data["categories"].items():
        for skill in category["skills"]:
            assert skill.get("proficiency") in allowed, (
                f"{category_name}/{skill.get('name')} has no valid proficiency tag"
            )
