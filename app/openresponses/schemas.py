"""Open Responses wire types.

This module is the **translation boundary**. Nothing in ``app/agent``,
``app/retrieval`` or ``app/tools`` imports from here, and nothing here knows how an
answer is produced. That separation is deliberate: the competition's protocol is a
front door, not an architecture, and it must be replaceable without touching the
system behind it.

Parsing is intentionally permissive on input and strict on output. Clients differ in
how they encode a turn — a bare string, a list of items, content as text or as
parts — and rejecting a valid-but-unfamiliar encoding would be a self-inflicted
integration failure. What we *emit* is held to the documented shape.
"""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ResponseStatus = Literal["queued", "in_progress", "completed", "failed", "incomplete"]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# --------------------------------------------------------------------------- #
# Request
# --------------------------------------------------------------------------- #


class ResponsesRequest(BaseModel):
    """A request to ``POST /v1/responses``.

    ``extra="allow"`` matters: the registration form lets the operator attach
    arbitrary extra parameters (its own example is
    ``{"temperature": 0.7, "reasoning": {"effort": "medium"}}``). Rejecting unknown
    fields would turn an operator's harmless configuration into a 422.
    """

    model_config = ConfigDict(extra="allow")

    model: str | None = None
    input: str | list[dict[str, Any]] = ""
    instructions: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    stream: bool = False
    store: bool = False
    previous_response_id: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None


def _text_from_content(content: Any) -> str:
    """Flatten a content field that may be a string or a list of typed parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                # input_text / output_text / text are all in circulation.
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(p for p in parts if p)
    return ""


class Turn(BaseModel):
    """One conversational turn, normalised out of whatever the client sent."""

    role: Literal["user", "assistant", "system", "developer"]
    text: str


def parse_transcript(request: ResponsesRequest) -> list[Turn]:
    """Normalise ``input`` into an ordered transcript.

    The platform's default conversation mode is *replay the transcript*: it resends
    the whole exchange each turn and expects the agent to hold no state. So this is
    the only place conversation history enters the system, and there is no session
    store anywhere behind it.
    """
    raw = request.input
    if isinstance(raw, str):
        return [Turn(role="user", text=raw)] if raw.strip() else []

    turns: list[Turn] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type", "message")
        if item_type not in {"message", None}:
            # function_call / function_call_output / reasoning items are ours to
            # emit, not the client's to drive. Ignoring them is safer than obeying.
            continue
        role = item.get("role", "user")
        if role not in {"user", "assistant", "system", "developer"}:
            role = "user"
        text = _text_from_content(item.get("content"))
        if text.strip():
            turns.append(Turn(role=role, text=text))
    return turns


# --------------------------------------------------------------------------- #
# Response
# --------------------------------------------------------------------------- #


class OutputTextContent(BaseModel):
    type: Literal["output_text"] = "output_text"
    text: str
    annotations: list[dict[str, Any]] = Field(default_factory=list)


class OutputMessage(BaseModel):
    type: Literal["message"] = "message"
    id: str = Field(default_factory=lambda: _new_id("msg"))
    status: Literal["completed", "incomplete"] = "completed"
    role: Literal["assistant"] = "assistant"
    content: list[OutputTextContent]


OutputItem = Annotated[OutputMessage, Field(discriminator="type")]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ResponseError(BaseModel):
    code: str
    message: str


class ResponseObject(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("resp"))
    object: Literal["response"] = "response"
    created_at: int = Field(default_factory=lambda: int(time.time()))
    status: ResponseStatus = "completed"
    model: str = "cv-agent"
    output: list[OutputItem] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    error: ResponseError | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def output_text(self) -> str:
        return "\n".join(part.text for item in self.output for part in item.content if part.text)


def text_response(
    text: str,
    *,
    model: str = "cv-agent",
    usage: Usage | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResponseObject:
    return ResponseObject(
        status="completed",
        model=model,
        output=[OutputMessage(content=[OutputTextContent(text=text)])],
        usage=usage or Usage(),
        metadata=metadata or {},
    )


def error_response(code: str, message: str, *, model: str = "cv-agent") -> ResponseObject:
    return ResponseObject(
        status="failed", model=model, error=ResponseError(code=code, message=message)
    )
