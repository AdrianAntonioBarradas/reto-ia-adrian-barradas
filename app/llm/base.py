"""The provider seam.

Everything above this module speaks in these types. Nothing above it knows which
vendor is answering, which is what makes swapping providers an environment change
rather than a refactor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool the model asked us to run. ``arguments`` is raw JSON text.

    ``provider_extra`` carries vendor-specific data that must be handed back
    verbatim on the next turn. Gemini 3 puts a ``thought_signature`` here and
    rejects the follow-up request without it; other providers leave it empty. The
    field is opaque on purpose — the loop moves it around without interpreting it,
    so a new provider's requirement costs nothing above the adapter.
    """

    id: str
    name: str
    arguments: str
    provider_extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    # Set on role="tool" messages to bind a result back to its request.
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""


@runtime_checkable
class LLMAdapter(Protocol):
    """Minimal surface: one turn in, one turn out. The loop lives in the agent."""

    @property
    def model(self) -> str: ...

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse: ...
