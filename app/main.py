"""FastAPI application.

Deliberately thin: routing, logging and the health surface. Everything with a
decision in it lives behind ``app.agent``.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api import agent_card, health, responses
from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)

settings = get_settings()

app = FastAPI(
    title="Agente de CV — Adrián Barradas",
    version="0.1.0",
    # The interactive docs describe an authenticated endpoint; there is nothing
    # secret in them, and leaving them up makes the deployment easier to inspect.
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.include_router(health.router, tags=["ops"])
app.include_router(agent_card.router, tags=["discovery"])
app.include_router(responses.router, tags=["open-responses"])


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "name": settings.agent_name,
        "open_responses_base_url": f"{settings.public_base_url.rstrip('/')}/v1",
        "agent_card": f"{settings.public_base_url.rstrip('/')}/.well-known/agent-card.json",
        "health": f"{settings.public_base_url.rstrip('/')}/health",
    }
