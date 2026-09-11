"""One adapter, four providers.

Google AI Studio, Cerebras, Groq and OpenAI all expose the same
``POST {base}/chat/completions`` shape, so a single implementation covers them.
Changing provider is three environment variables:

    LLM_BASE_URL   https://generativelanguage.googleapis.com/v1beta/openai
                   https://api.cerebras.ai/v1
                   https://api.groq.com/openai/v1
                   https://api.openai.com/v1
    LLM_MODEL
    LLM_API_KEY

Anthropic uses a different wire format and would need its own implementation of
``LLMAdapter``; nothing above this module would change.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.llm.base import ChatMessage, LLMResponse, ToolCall, ToolSpec


class LLMError(RuntimeError):
    """Provider call failed. Carries the status so the API layer can map it."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _message_to_wire(message: ChatMessage) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": message.role}
    # A tool result must carry content even when empty, or providers reject the turn.
    wire["content"] = message.content if message.content is not None else ""
    if message.tool_call_id is not None:
        wire["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
        # Providers disagree on whether content may be null alongside tool_calls;
        # an empty string is accepted everywhere.
        wire["content"] = message.content or ""
    return wire


def _tool_to_wire(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _parse_tool_calls(raw: list[dict[str, Any]] | None) -> tuple[ToolCall, ...]:
    if not raw:
        return ()
    calls: list[ToolCall] = []
    for index, item in enumerate(raw):
        function = item.get("function") or {}
        name = function.get("name")
        if not name:
            continue
        calls.append(
            ToolCall(
                # Some providers omit the id; the agent loop needs one to pair results.
                id=str(item.get("id") or f"call_{index}"),
                name=str(name),
                arguments=str(function.get("arguments") or "{}"),
            )
        )
    return tuple(calls)


class OpenAICompatibleAdapter:
    """Chat-completions client for any OpenAI-shaped provider."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        max_output_tokens: int = 1024,
        temperature: float = 0.2,
        timeout_s: float = 45.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._timeout_s = timeout_s
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise LLMError("LLM_API_KEY is not configured", status_code=503)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_message_to_wire(m) for m in messages],
            "max_completion_tokens": self._max_output_tokens,
            "temperature": self._temperature,
        }
        if tools:
            payload["tools"] = [_tool_to_wire(t) for t in tools]
            payload["tool_choice"] = "auto"

        client = self._client or httpx.AsyncClient(timeout=self._timeout_s)
        should_close = self._client is None
        try:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:  # network, DNS, timeout
            raise LLMError(f"LLM request failed: {exc}") from exc
        finally:
            if should_close:
                await client.aclose()

        if response.status_code >= 400:
            # Never echo the provider body verbatim: it can contain the key.
            raise LLMError(
                f"LLM provider returned {response.status_code}",
                status_code=response.status_code,
            )

        try:
            body = response.json()
            choice = body["choices"][0]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            raise LLMError("LLM provider returned an unexpected body") from exc

        message = choice.get("message") or {}
        return LLMResponse(
            content=message.get("content"),
            tool_calls=_parse_tool_calls(message.get("tool_calls")),
            finish_reason=str(choice.get("finish_reason") or "stop"),
            usage={k: int(v) for k, v in (body.get("usage") or {}).items() if isinstance(v, int)},
            model=str(body.get("model") or self._model),
        )


def build_llm_adapter(
    settings: Settings | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> OpenAICompatibleAdapter:
    cfg = settings or get_settings()
    return OpenAICompatibleAdapter(
        base_url=cfg.llm_base_url,
        api_key=cfg.llm_api_key,
        model=cfg.llm_model,
        max_output_tokens=cfg.llm_max_output_tokens,
        temperature=cfg.llm_temperature,
        timeout_s=cfg.llm_timeout_s,
        client=client,
    )
