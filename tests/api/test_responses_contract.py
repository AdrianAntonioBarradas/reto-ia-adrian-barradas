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
    response = await client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    card = response.json()
    assert card["url"].endswith("/v1")
    assert card["security"] == [{"bearer": []}]
    assert {s["id"] for s in card["skills"]} == {
        "perfil",
        "experiencia",
        "habilidades",
        "proyectos",
    }
