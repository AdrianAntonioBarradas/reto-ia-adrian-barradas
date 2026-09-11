"""Agent orchestration.

Currently a stub that proves the transport end to end. The tool loop, policy gate
and retrieval land behind this same signature, so the API layer never changes.
"""

from __future__ import annotations

from app.agent.types import AgentAnswer
from app.openresponses.schemas import Turn

_STUB_REPLY = (
    "El agente está en construcción: el transporte compatible con Open Responses "
    "ya funciona, pero la capa de recuperación y generación todavía no está conectada."
)


async def answer(turns: list[Turn], instructions: str | None = None) -> AgentAnswer:
    """Answer the last user turn given the full replayed transcript."""
    del instructions  # honoured once generation is wired in
    last_user = next((t.text for t in reversed(turns) if t.role == "user"), "")
    if not last_user.strip():
        return AgentAnswer(text="¿En qué te puedo ayudar sobre el perfil de Adrián?")
    return AgentAnswer(text=_STUB_REPLY, short_circuited="stub")
