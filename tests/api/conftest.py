from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

TEST_KEY = "test-agent-key"


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENT_API_KEY", TEST_KEY)
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("RETRIEVAL_MODE", "structured")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _stub_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise the transport, not the agent.

    Letting them reach the real loop would make the Open Responses contract depend on
    an LLM being reachable and well-behaved, which is exactly the coupling the
    translation boundary exists to prevent. The agent has its own tests.
    """
    from app.agent import loop
    from app.agent.types import AgentAnswer

    async def fake_answer(
        turns: object, instructions: object = None, client_tools: object = None
    ) -> AgentAnswer:
        return AgentAnswer(text="respuesta de prueba", usage={"total_tokens": 7})

    monkeypatch.setattr(loop, "answer", fake_answer)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_KEY}"}
