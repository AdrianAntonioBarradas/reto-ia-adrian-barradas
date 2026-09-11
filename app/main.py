"""FastAPI application.

Deliberately thin: routing, logging and the health surface. Everything with a
decision in it lives behind ``app.agent``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import agent_card, health, responses
from app.config import get_settings

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Build the retrieval index before accepting traffic.

    Loading it lazily on the first request meant the first *user* paid several
    seconds for it — and worse, that an out-of-memory kill happened mid-request and
    looked like a 502 from a healthy service. Doing it here makes the failure
    happen at boot, where the healthcheck catches it and the deploy is not promoted.
    """
    from app.retrieval.engine import get_engine

    engine = get_engine(settings)
    logger.info(
        "retrieval index ready",
        extra={"mode": engine.mode, "chunks": engine.chunk_count},
    )
    yield


app = FastAPI(
    lifespan=lifespan,
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
