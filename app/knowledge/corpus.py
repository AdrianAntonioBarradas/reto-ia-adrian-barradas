"""Load the curated public corpus.

The YAML files under ``data/canonical/`` are the source of truth. Everything else —
chunks, embeddings, indexes — is derived, and can be deleted and rebuilt without
losing knowledge. That distinction is what makes re-indexing a safe operation rather
than a data migration.

The corpus is small, static and ships with the repository, so it is loaded once at
startup and held in memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CANONICAL_DIR = Path(__file__).resolve().parents[2] / "data" / "canonical"

PROFICIENCY_ORDER = {
    "PROVEN": 5,
    "EXPERIENCED": 4,
    "PROJECT": 3,
    "FAMILIAR": 2,
    "LEARNING": 1,
}


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    proficiency: str
    domains: tuple[str, ...]
    category: str
    category_label: str
    note: str | None = None

    @property
    def rank(self) -> int:
        return PROFICIENCY_ORDER.get(self.proficiency, 0)


@dataclass(frozen=True, slots=True)
class Corpus:
    """The whole public profile, parsed. Read-only by construction."""

    profile: dict[str, Any]
    education: list[dict[str, Any]]
    experience: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    skills: tuple[Skill, ...]
    skill_categories: dict[str, str]
    domain_knowledge: dict[str, Any]
    policy: dict[str, Any]

    def project(self, project_id: str) -> dict[str, Any] | None:
        return next((p for p in self.projects if p["id"] == project_id), None)

    def experience_entry(self, entry_id: str) -> dict[str, Any] | None:
        return next((e for e in self.experience if e["id"] == entry_id), None)

    def skills_in_category(self, category: str) -> tuple[Skill, ...]:
        return tuple(s for s in self.skills if s.category == category)


def _read(name: str, directory: Path) -> dict[str, Any]:
    data = yaml.safe_load((directory / name).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{name} did not parse to a mapping")
    return data


def load_corpus(directory: Path | None = None) -> Corpus:
    base = directory or CANONICAL_DIR

    profile = _read("profile.yaml", base)
    education = _read("education.yaml", base)
    experience = _read("experience.yaml", base)
    projects = _read("projects.yaml", base)
    skills_doc = _read("skills.yaml", base)
    policy = _read("policy.yaml", base)

    skills: list[Skill] = []
    categories: dict[str, str] = {}
    for category, block in skills_doc["categories"].items():
        categories[category] = block.get("label", category)
        for entry in block["skills"]:
            skills.append(
                Skill(
                    name=entry["name"],
                    proficiency=entry["proficiency"],
                    domains=tuple(entry.get("domains", ())),
                    category=category,
                    category_label=categories[category],
                    note=entry.get("note"),
                )
            )

    return Corpus(
        profile=profile,
        education=education["education"],
        experience=experience["experience"],
        projects=projects["projects"],
        skills=tuple(skills),
        skill_categories=categories,
        domain_knowledge=skills_doc.get("domain_knowledge", {}),
        policy=policy,
    )


@lru_cache(maxsize=1)
def get_corpus() -> Corpus:
    return load_corpus()
