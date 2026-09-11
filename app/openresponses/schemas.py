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
from collections.abc import Sequence
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


class FunctionCallItem(BaseModel):
    """A call to a tool the *caller* declared.

    The caller executes it and returns a ``function_call_output`` on the next turn.
    The agent's own tools never appear here — those run server-side inside the loop
    and only their effect on the answer is visible.
    """

    type: Literal["function_call"] = "function_call"
    id: str = Field(default_factory=lambda: _new_id("fc"))
    call_id: str
    name: str
    arguments: str
    status: Literal["completed", "in_progress", "incomplete"] = "completed"


OutputItem = Annotated[OutputMessage | FunctionCallItem, Field(discriminator="type")]


class InputTokensDetails(BaseModel):
    cached_tokens: int = 0


class OutputTokensDetails(BaseModel):
    reasoning_tokens: int = 0


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_tokens_details: InputTokensDetails = Field(default_factory=InputTokensDetails)
    output_tokens_details: OutputTokensDetails = Field(default_factory=OutputTokensDetails)


class ResponseError(BaseModel):
    code: str
    message: str


class IncompleteDetails(BaseModel):
    reason: str


class TextFormat(BaseModel):
    type: Literal["text"] = "text"


class TextField(BaseModel):
    format: TextFormat = Field(default_factory=TextFormat)


class ResponseObject(BaseModel):
    """A response, as the specification defines it.

    Every one of these fields is **required** — the schema has no optional
    properties. That was not obvious from reading the prose, and it is the reason
    this object is so much larger than it looks like it needs to be: a CV agent has
    no use for ``top_logprobs`` or ``frequency_penalty``, but a conformant response
    carries them anyway, echoing what was in effect for the turn.

    This was found by running the specification's own compliance suite against the
    deployed endpoint, not by reading the spec. The hand-written contract tests in
    ``tests/api/`` had passed all along, because the same incomplete understanding
    wrote both the tests and the implementation. A test you wrote from your own
    reading cannot tell you that your reading was wrong.
    """

    id: str = Field(default_factory=lambda: _new_id("resp"))
    object: Literal["response"] = "response"
    created_at: int = Field(default_factory=lambda: int(time.time()))
    completed_at: int | None = None
    status: ResponseStatus = "completed"
    model: str = "cv-agent"
    output: list[OutputItem] = Field(default_factory=list)

    error: ResponseError | None = None
    incomplete_details: IncompleteDetails | None = None
    usage: Usage | None = Field(default_factory=Usage)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Echoed request configuration. The agent does not act on most of these, but a
    # conformant response reports what was in effect.
    instructions: str | None = None
    previous_response_id: str | None = None
    max_output_tokens: int | None = None
    max_tool_calls: int | None = None
    prompt_cache_key: str | None = None
    safety_identifier: str | None = None
    reasoning: dict[str, Any] | None = None
    text: TextField = Field(default_factory=TextField)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: str = "auto"
    truncation: Literal["auto", "disabled"] = "disabled"
    parallel_tool_calls: bool = True
    store: bool = False
    background: bool = False
    service_tier: str = "default"
    temperature: float = 1.0
    top_p: float = 1.0
    top_logprobs: int = 0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0

    @property
    def output_text(self) -> str:
        return "\n".join(
            part.text
            for item in self.output
            if isinstance(item, OutputMessage)
            for part in item.content
            if part.text
        )


def _normalize_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Bring a caller's tool declaration up to the *response* schema.

    A request may omit fields the response requires. ``strict`` is the one that bit:
    the compliance suite declares a tool without it, and echoing the declaration back
    verbatim failed validation with `tools.0.strict: Invalid input`. The request and
    response schemas for a tool are not the same shape, and assuming they were is an
    easy mistake to make when the field names line up.
    """
    nested = tool.get("function")
    body: dict[str, Any] = nested if isinstance(nested, dict) else tool
    return {
        "type": "function",
        "name": body.get("name", ""),
        "description": body.get("description"),
        "parameters": body.get("parameters") or {"type": "object", "properties": {}},
        "strict": body.get("strict", False),
    }


def _echo_request(response: ResponseObject, request: ResponsesRequest | None) -> ResponseObject:
    """Reflect the caller's own settings back, as the schema expects."""
    if request is None:
        return response
    response.instructions = request.instructions
    response.previous_response_id = request.previous_response_id
    response.max_output_tokens = request.max_output_tokens
    response.store = bool(request.store)
    response.tools = [_normalize_tool(t) for t in (request.tools or []) if isinstance(t, dict)]
    if isinstance(request.tool_choice, str):
        response.tool_choice = request.tool_choice
    if request.temperature is not None:
        response.temperature = request.temperature
    return response


def text_response(
    text: str,
    *,
    model: str = "cv-agent",
    usage: Usage | None = None,
    metadata: dict[str, Any] | None = None,
    request: ResponsesRequest | None = None,
    function_calls: Sequence[tuple[str, str, str]] = (),
) -> ResponseObject:
    """Build a completed response.

    ``function_calls`` is a sequence of ``(call_id, name, arguments)`` for tools the
    caller declared and must execute itself.
    """
    now = int(time.time())
    output: list[OutputItem] = []
    if text.strip():
        output.append(OutputMessage(content=[OutputTextContent(text=text)]))
    output.extend(
        FunctionCallItem(call_id=call_id, name=name, arguments=arguments)
        for call_id, name, arguments in function_calls
    )
    response = ResponseObject(
        status="completed",
        created_at=now,
        completed_at=now,
        model=model,
        output=output,
        usage=usage or Usage(),
        metadata=metadata or {},
    )
    return _echo_request(response, request)


def error_response(
    code: str,
    message: str,
    *,
    model: str = "cv-agent",
    request: ResponsesRequest | None = None,
) -> ResponseObject:
    response = ResponseObject(
        status="failed",
        model=model,
        error=ResponseError(code=code, message=message),
    )
    return _echo_request(response, request)
