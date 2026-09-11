"""Liveness and readiness.

The platform's healthcheck points here. It reports 503 rather than 200-with-a-flag
when a dependency is down, so a broken deploy is never promoted.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.config import get_settings

router = APIRouter()


@router.get("/health")
async def health(response: Response) -> dict[str, Any]:
    settings = get_settings()
    checks: dict[str, str] = {}

    # The API key being configured is a readiness condition, not a nicety: without
    # it every request would 503 anyway.
    checks["api_key"] = "ok" if settings.agent_api_key else "missing"
    checks["llm_api_key"] = "ok" if settings.llm_api_key else "missing"

    healthy = all(value == "ok" for value in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if healthy else "degraded",
        "environment": settings.environment,
        "retrieval_mode": settings.retrieval_mode,
        "checks": checks,
    }
