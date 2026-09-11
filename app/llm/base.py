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
    # The provider's own representation of an assistant turn, replayed verbatim.
    #
    # Reasoning models attach state to their turn that must come back unchanged:
    # Anthropic's thinking blocks, Gemini's thought signatures. Reconstructing the
    # turn from text and tool calls silently drops it, and the failure only appears
    # on the *next* request. When this is set the adapter sends it as-is.
    provider_raw: tuple[dict[str, Any], ...] | None = None


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
    # Hand back to the next turn's assistant ChatMessage. See ChatMessage.provider_raw.
    provider_raw: tuple[dict[str, Any], ...] | None = None


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
