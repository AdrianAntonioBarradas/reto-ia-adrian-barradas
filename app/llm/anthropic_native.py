"""Anthropic adapter, on the official SDK.

Anthropic does not speak the OpenAI chat-completions shape, and the OpenAI-compat
shims that exist are migration aids rather than a supported production surface. So
this is a second implementation of ``LLMAdapter`` rather than a base-URL swap — which
is precisely what the Protocol was for: nothing above ``app/llm/`` changes.

Two details that are easy to get wrong and fail only on the second turn:

* **Thinking blocks must be replayed unchanged.** Adaptive thinking is on by default
  on current models, and the assistant turn carries thinking blocks that have to come
  back verbatim with the tool results. Rebuilding the turn from text alone drops
  them. That is what ``provider_raw`` exists for.
* **Tool results are user-role content blocks**, not a separate ``tool`` role, and
  every result for one assistant turn belongs in a *single* user message. Splitting
  them across messages teaches the model to stop making parallel calls.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import (
    APIConnectionError,
    APIStatusError,
    AsyncAnthropic,
    RateLimitError,
)

from app.config import Settings, get_settings
from app.llm.base import ChatMessage, LLMResponse, ToolCall, ToolSpec
from app.llm.errors import LLMError

logger = logging.getLogger(__name__)


def _to_anthropic_messages(
    messages: list[ChatMessage],
) -> tuple[str, list[dict[str, Any]]]:
    """Split the system prompt out and fold tool results into user turns."""
    system_parts: list[str] = []
    turns: list[dict[str, Any]] = []
    pending_results: list[dict[str, Any]] = []

    def flush_results() -> None:
        if pending_results:
            turns.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
            continue

        if message.role == "tool":
            pending_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.content or "",
                }
            )
            continue

        flush_results()

        if message.role == "assistant":
            if message.provider_raw is not None:
                # Verbatim replay: keeps thinking blocks intact.
                turns.append({"role": "assistant", "content": list(message.provider_raw)})
                continue
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": json.loads(call.arguments or "{}"),
                    }
                )
            if blocks:
                turns.append({"role": "assistant", "content": blocks})
            continue

        turns.append({"role": "user", "content": message.content or ""})

    flush_results()
    return "\n\n".join(system_parts), turns


class AnthropicAdapter:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_output_tokens: int = 8192,
        effort: str = "low",
        timeout_s: float = 60.0,
        client: AsyncAnthropic | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        # Thinking tokens count against max_tokens, so this needs headroom well
        # beyond the visible answer or the response truncates mid-thought.
        self._max_output_tokens = max_output_tokens
        self._effort = effort
        self._timeout_s = timeout_s
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            self._client = AsyncAnthropic(api_key=self._api_key, timeout=self._timeout_s)
        return self._client

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise LLMError("LLM_API_KEY is not configured", status_code=503)

        system, turns = _to_anthropic_messages(messages)
        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_output_tokens,
            "messages": turns,
            # Answering a grounded question from retrieved evidence is not a hard
            # reasoning task; low effort keeps latency and cost down. Thinking
            # itself stays on — disabling it on current models has its own failure
            # modes, including tool calls written into visible text.
            "output_config": {"effort": self._effort},
        }
        if system:
            request["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        if tools:
            request["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]

        try:
            response = await self._get_client().messages.create(**request)
        except RateLimitError as exc:
            raise LLMError("LLM provider rate limited", status_code=429) from exc
        except APIStatusError as exc:
            logger.warning(
                "llm provider error",
                extra={"status": exc.status_code, "model": self._model, "detail": str(exc)[:500]},
            )
            raise LLMError(
                f"LLM provider returned {exc.status_code}: {str(exc)[:300]}",
                status_code=exc.status_code,
            ) from exc
        except APIConnectionError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        raw: list[dict[str, Any]] = []
        for block in response.content:
            raw.append(block.model_dump(exclude_none=True))
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=json.dumps(block.input, ensure_ascii=False),
                    )
                )

        usage = response.usage
        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tuple(calls),
            finish_reason=response.stop_reason or "end_turn",
            usage={
                "prompt_tokens": usage.input_tokens,
                "completion_tokens": usage.output_tokens,
                "total_tokens": usage.input_tokens + usage.output_tokens,
            },
            model=response.model,
            provider_raw=tuple(raw),
        )


def build_anthropic_adapter(settings: Settings | None = None) -> AnthropicAdapter:
    cfg = settings or get_settings()
    return AnthropicAdapter(
        api_key=cfg.llm_api_key,
        model=cfg.llm_model,
        max_output_tokens=cfg.llm_max_output_tokens,
        effort=cfg.llm_effort,
        timeout_s=cfg.llm_timeout_s,
    )
