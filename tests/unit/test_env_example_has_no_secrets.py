"""``.env.example`` is a committed, public document. It must never hold a real value.

This exists because a real key was once pasted into it. The file's job is to be the
environment *contract* — which variables exist, where to obtain each one, and what an
empty value means — and a contract with a live credential in it is a leak waiting for
the next ``git add -A``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

# Provider key formats, by prefix. Matching on shape rather than entropy keeps the
# check readable and avoids flagging ordinary placeholder text.
SECRET_SHAPES: dict[str, str] = {
    "Google AI Studio": r"AIza[0-9A-Za-z_\-]{30,}",
    "Anthropic": r"sk-ant-[0-9A-Za-z_\-]{20,}",
    "OpenAI": r"sk-(?!ant-)[0-9A-Za-z_\-]{20,}",
    "Cerebras": r"csk-[0-9a-z]{20,}",
    "Groq": r"gsk_[0-9A-Za-z]{20,}",
    "Voyage": r"pa-[0-9A-Za-z_\-]{20,}",
    "GitHub token": r"gh[pousr]_[0-9A-Za-z]{20,}",
    "Postgres URL with a password": r"postgres(?:ql)?://[^:\s]+:(?!cvagent@)[^@\s]{8,}@",
}


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file(), ".env.example is the environment contract and must exist"


@pytest.mark.parametrize("provider", sorted(SECRET_SHAPES))
def test_env_example_contains_no_real_credential(provider: str) -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    match = re.search(SECRET_SHAPES[provider], text)
    assert match is None, (
        f".env.example appears to contain a real {provider} credential. "
        "Move it to .env (which is gitignored) and restore the placeholder here. "
        "Then rotate the key, because it existed in a tracked file."
    )


def test_every_key_variable_is_left_empty() -> None:
    """No ``*_KEY`` or ``*_TOKEN`` variable may carry a value in the template."""
    offenders: list[str] = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        if name.endswith(("_KEY", "_TOKEN", "_SECRET")) and value.strip():
            offenders.append(name)
    assert not offenders, (
        f"these variables have a value in .env.example: {offenders}. "
        "The template documents variables; it never carries their values."
    )


def test_env_example_documents_every_setting() -> None:
    """The template is only a contract if it is complete.

    Drift here is quiet and expensive: a variable that exists in ``Settings`` but not
    in ``.env.example`` is one nobody knows to set on the deployment platform, and it
    surfaces as a runtime default rather than as an error.
    """
    from app.config import Settings

    declared = {
        line.strip().partition("=")[0].strip()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#") and "=" in line
    }
    expected = {name.upper() for name in Settings.model_fields}
    missing = sorted(expected - declared)
    unknown = sorted(declared - expected)
    assert not missing, f".env.example does not document: {missing}"
    assert not unknown, f".env.example documents variables Settings does not read: {unknown}"
