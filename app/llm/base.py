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
    """A tool the model asked us to run. ``arguments`` is raw JSON text."""

    id: str
    name: str
    arguments: str


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
