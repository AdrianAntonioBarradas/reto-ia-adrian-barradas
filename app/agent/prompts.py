"""Compose the system prompt from layered markdown.

The prompt lives in ``agent/prompts/*.md`` rather than in a Python string for two
reasons: it is content, not code, so it should be reviewable as prose in a diff; and
keeping the honesty policy beside the corpus that encodes it makes the pair easy to
change together.

Files are concatenated in filename order, which is why they are numbered.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

# Resolved from the repository root, not the working directory: the process may be
# started from anywhere.
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "agent" / "prompts"


@lru_cache(maxsize=1)
def compose_system_prompt() -> str:
    parts = [path.read_text(encoding="utf-8").strip() for path in sorted(PROMPTS_DIR.glob("*.md"))]
    if not parts:
        raise RuntimeError(f"no prompt layers found in {PROMPTS_DIR}")
    return "\n\n---\n\n".join(parts)


def with_operator_instructions(base: str, instructions: str | None) -> str:
    """Append the operator's per-request ``instructions`` field, subordinated.

    The Open Responses registration form lets whoever registers the agent attach
    standing instructions. Honouring them is correct — they come from the operator,
    not from the end user — but they are appended *after* the core policy and framed
    as additional, so they can shape tone or emphasis without overriding the
    grounding and honesty rules.
    """
    if not instructions or not instructions.strip():
        return base
    return (
        f"{base}\n\n---\n\n"
        "# Instrucciones adicionales del operador\n\n"
        "Las siguientes indicaciones vienen de quien registró este agente. Respétalas "
        "siempre que no contradigan las reglas anteriores sobre evidencia, honestidad "
        "de nivel y autoría, que no son negociables.\n\n"
        f"{instructions.strip()}"
    )
