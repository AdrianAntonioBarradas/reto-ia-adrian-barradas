"""The corpus must match its manifest.

docs/SECURITY.md claims checksummed sources as the control against data poisoning
(LLM03). This is that claim made real: without an executable check, the manifest is a
file that drifts and the claim is decoration.
"""

from __future__ import annotations

from scripts.manifest import MANIFEST, build, differences, load


def test_manifest_exists() -> None:
    assert MANIFEST.is_file(), "no corpus manifest: run `uv run python -m scripts.manifest --write`"


def test_corpus_matches_its_manifest() -> None:
    recorded = load()
    assert recorded is not None
    problems = differences(build(), recorded)
    assert not problems, (
        "the canonical corpus has changed without its manifest being regenerated:\n  "
        + "\n  ".join(problems)
        + "\n\nIf the change was intended, run `uv run python -m scripts.manifest --write` "
        "and commit both."
    )


def test_manifest_records_a_corpus_wide_digest() -> None:
    """One value that names the whole corpus, so a result can cite what it ran against."""
    recorded = load()
    assert recorded is not None
    assert len(recorded["corpus_sha256"]) == 64
    assert recorded["file_count"] == len(recorded["files"])
