"""The Open Responses contract.

These tests encode what the Reto IA platform will actually send and what it must
receive back. They are the regression gate on the integration: retrieval quality can
change freely underneath, but the wire shape may not drift.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

ENDPOINT = "/v1/responses"


async def test_rejects_request_without_token(client: AsyncClient) -> None:
    response = await client.post(ENDPOINT, json={"input": "hola"})
    assert response.status_code == 401


async def test_rejects_request_with_wrong_token(client: AsyncClient) -> None:
    response = await client.post(
        ENDPOINT, json={"input": "hola"}, headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 401


async def test_refuses_everything_when_key_is_unset(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unset secret must fail closed, never open."""
    from app.config import get_settings

    monkeypatch.setenv("AGENT_API_KEY", "")
    get_settings.cache_clear()
    response = await client.post(
        ENDPOINT, json={"input": "hola"}, headers={"Authorization": "Bearer anything"}
    )
    assert response.status_code == 503


async def test_accepts_bare_string_input(client: AsyncClient, auth: dict[str, str]) -> None:
    response = await client.post(ENDPOINT, json={"input": "¿Qué hizo en Cicada?"}, headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["id"].startswith("resp_")
    assert isinstance(body["created_at"], int)


async def test_emits_a_well_formed_output_message(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    response = await client.post(ENDPOINT, json={"input": "hola"}, headers=auth)
    output = response.json()["output"]
    assert len(output) == 1
    item = output[0]
    assert item["type"] == "message"
    assert item["role"] == "assistant"
    assert item["id"].startswith("msg_")
    assert item["content"][0]["type"] == "output_text"
    assert item["content"][0]["text"].strip()


async def test_accepts_item_array_input_with_content_parts(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """The transcript-replay shape the platform sends by default."""
    payload: dict[str, Any] = {
        "model": "cv-agent",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "¿Qué experiencia tiene con Go?"}],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Trabajó con Go en Cicada."}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "¿Y con Python?"}],
            },
        ],
    }
    response = await client.post(ENDPOINT, json=payload, headers=auth)
    assert response.status_code == 200
    assert response.json()["model"] == "cv-agent"


async def test_tolerates_unknown_extra_parameters(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """The registration form lets operators attach arbitrary extra parameters."""
    payload = {
        "input": "hola",
        "temperature": 0.7,
        "reasoning": {"effort": "medium"},
        "service_tier": "auto",
        "unknown_future_field": True,
    }
    response = await client.post(ENDPOINT, json=payload, headers=auth)
    assert response.status_code == 200


async def test_usage_block_is_always_present(client: AsyncClient, auth: dict[str, str]) -> None:
    body = (await client.post(ENDPOINT, json={"input": "hola"}, headers=auth)).json()
    assert set(body["usage"]) >= {"input_tokens", "output_tokens", "total_tokens"}


async def test_empty_input_still_returns_a_valid_response(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    response = await client.post(ENDPOINT, json={"input": ""}, headers=auth)
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


async def test_agent_failure_returns_a_failed_response_not_a_500(
    client: AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chat UI can render a failed response object; it cannot render a stack trace."""
    from app.agent import loop

    async def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(loop, "answer", boom)
    response = await client.post(ENDPOINT, json={"input": "hola"}, headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "agent_error"
    assert "provider exploded" not in response.text


async def test_health_reports_degraded_when_a_key_is_missing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    response = await client.get("/health")
    assert response.status_code == 503
    assert response.json()["checks"]["llm_api_key"] == "missing"


async def test_agent_card_is_servable_and_points_at_the_v1_base(client: AsyncClient) -> None:
    """The card must match A2A v1.0, not the older single-`url` shape.

    The registration form rejected the first version outright — "falta name o
    supportedInterfaces" — because v1.0 replaced the top-level url/preferredTransport
    pair with a list of interfaces, each carrying its own binding and version.
    """
    response = await client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    card = response.json()

    assert card["name"]
    interfaces = card["supportedInterfaces"]
    assert len(interfaces) == 1
    assert interfaces[0]["url"].endswith("/v1")
    # HTTP+JSON, not JSONRPC: the card should describe what the endpoint actually is.
    assert interfaces[0]["protocolBinding"] == "HTTP+JSON"
    assert interfaces[0]["protocolVersion"]

    assert card["capabilities"]["streaming"] is True
    assert "bearer" in card["securitySchemes"]
    assert card["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]["scheme"] == "bearer"
    assert card["securityRequirements"]

    assert {s["id"] for s in card["skills"]} == {
        "perfil",
        "experiencia",
        "habilidades",
        "proyectos",
    }


async def test_agent_card_uses_camel_case_not_the_protobuf_names(
    client: AsyncClient,
) -> None:
    """The normative spec is protobuf (snake_case); the JSON binding is camelCase."""
    card = (await client.get("/.well-known/agent-card.json")).json()
    for wrong in ("supported_interfaces", "security_requirements", "security_schemes"):
        assert wrong not in card, f"card uses the protobuf name {wrong!r}"


# --- streaming ---------------------------------------------------------------


def _parse_sse(body: str) -> list[dict[str, Any]]:
    """Parse an SSE body into event payloads, ignoring the [DONE] sentinel."""
    import json

    events: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if data and data != "[DONE]":
                    events.append(json.loads(data))
    return events


async def test_streaming_sets_the_event_stream_content_type(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    response = await client.post(ENDPOINT, json={"input": "hola", "stream": True}, headers=auth)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


async def test_streaming_emits_the_documented_event_sequence(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    body = (await client.post(ENDPOINT, json={"input": "hola", "stream": True}, headers=auth)).text
    types = [e["type"] for e in _parse_sse(body)]
    assert types[0] == "response.created"
    assert types[1] == "response.in_progress"
    assert types[-1] == "response.completed"
    for expected in (
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
    ):
        assert expected in types, f"missing {expected}"


async def test_streaming_terminates_with_the_done_sentinel(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    body = (await client.post(ENDPOINT, json={"input": "hola", "stream": True}, headers=auth)).text
    assert body.rstrip().endswith("data: [DONE]")


async def test_every_streaming_event_carries_a_monotonic_sequence_number(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """sequence_number is required on every event schema, and ordering is the point."""
    body = (await client.post(ENDPOINT, json={"input": "hola", "stream": True}, headers=auth)).text
    numbers = [e["sequence_number"] for e in _parse_sse(body)]
    assert numbers == sorted(numbers)
    assert numbers == list(range(1, len(numbers) + 1))


async def test_deltas_reassemble_into_the_final_text(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """A client that concatenates deltas must end up with exactly the answer."""
    body = (await client.post(ENDPOINT, json={"input": "hola", "stream": True}, headers=auth)).text
    events = _parse_sse(body)
    deltas = "".join(e["delta"] for e in events if e["type"] == "response.output_text.delta")
    done = next(e["text"] for e in events if e["type"] == "response.output_text.done")
    assert deltas == done
    final = next(e for e in events if e["type"] == "response.completed")
    assert final["response"]["output"][0]["content"][0]["text"] == deltas


async def test_terminal_event_carries_the_full_response_object(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    body = (await client.post(ENDPOINT, json={"input": "hola", "stream": True}, headers=auth)).text
    final = next(e for e in _parse_sse(body) if e["type"] == "response.completed")
    response = final["response"]
    assert response["status"] == "completed"
    # The schema has no optional properties; spot-check ones easily forgotten.
    for field in ("service_tier", "truncation", "parallel_tool_calls", "top_logprobs"):
        assert field in response, f"terminal response is missing {field}"


async def test_client_declared_tools_come_back_as_function_call_items(
    client: AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caller-supplied tools are the caller's to execute, not ours."""
    from app.agent import loop
    from app.agent.types import AgentAnswer, PendingToolCall

    async def fake_answer(
        turns: object, instructions: object = None, client_tools: object = None
    ) -> AgentAnswer:
        return AgentAnswer(
            text="",
            pending_tool_calls=(
                PendingToolCall(id="call_1", name="get_weather", arguments='{"location":"SF"}'),
            ),
        )

    monkeypatch.setattr(loop, "answer", fake_answer)
    payload = {
        "input": "What's the weather in San Francisco?",
        "tools": [
            {
                "type": "function",
                "name": "get_weather",
                "description": "Get the current weather",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
    }
    body = (await client.post(ENDPOINT, json=payload, headers=auth)).json()
    calls = [item for item in body["output"] if item["type"] == "function_call"]
    assert len(calls) == 1
    assert calls[0]["name"] == "get_weather"
    assert calls[0]["call_id"] == "call_1"
    # The response must echo the caller's tools, brought up to the response schema:
    # `strict` is required there even when the request omitted it.
    echoed = body["tools"][0]
    assert echoed["name"] == "get_weather"
    assert echoed["type"] == "function"
    assert "strict" in echoed
    assert "parameters" in echoed
