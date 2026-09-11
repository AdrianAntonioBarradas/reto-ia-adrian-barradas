"""Bearer-token check for the public endpoint.

Fail-closed with no environment bypass: if ``AGENT_API_KEY`` is unset the API
refuses everything, in development as well as production. An unset secret must
never be read as "open" — that is the single most common way a demo endpoint ends
up unauthenticated on the public internet.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().agent_api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="agent is not configured to accept requests",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    presented = authorization.split(" ", 1)[1].strip()
    # Constant-time: a timing oracle on a short token is a real distinguisher.
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
