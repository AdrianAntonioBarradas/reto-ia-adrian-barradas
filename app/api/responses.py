"""``POST /v1/responses`` — the public contract.

The platform registers a *base URL* and appends ``/responses``, so registering
``https://<host>/v1`` lands requests here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.agent import loop
from app.api.security import require_api_key
from app.config import get_settings
from app.openresponses.schemas import (
    ResponseObject,
    ResponsesRequest,
    Usage,
    error_response,
    parse_transcript,
    text_response,
)
from app.openresponses.stream import astream_response

logger = logging.getLogger(__name__)
router = APIRouter()


# response_model=None: the return type is a union of a Pydantic model and a
# StreamingResponse, which FastAPI cannot turn into a single response schema.
@router.post("/v1/responses", response_model=None)
async def create_response(
    body: ResponsesRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> ResponseObject | StreamingResponse:
    settings = get_settings()
    model_label = body.model or "cv-agent"
    turns = parse_transcript(body)

    try:
        result = await loop.answer(turns, instructions=body.instructions, client_tools=body.tools)
    except Exception:
        # Never leak an internal error to the caller, and never 500 the platform:
        # a failed *response object* is more useful to a chat UI than a stack trace.
        logger.exception("agent failed", extra={"request_id": request.headers.get("x-request-id")})
        failure = error_response(
            "agent_error",
            "El agente no pudo completar la respuesta.",
            model=model_label,
            request=body,
        )
        if body.stream:
            return StreamingResponse(astream_response(failure), media_type="text/event-stream")
        return failure

    # Privacy-aware telemetry: what was asked *about*, never what was said.
    logger.info(
        "responses.completed",
        extra={
            "turns": len(turns),
            "retrieval_mode": settings.retrieval_mode,
            "tool_calls": list(result.tool_calls_made),
            "evidence": [e.source_id for e in result.evidence],
            "short_circuited": result.short_circuited,
            "pending_tool_calls": [c.name for c in result.pending_tool_calls],
        },
    )

    usage = Usage(
        input_tokens=result.usage.get("prompt_tokens", 0),
        output_tokens=result.usage.get("completion_tokens", 0),
        total_tokens=result.usage.get("total_tokens", 0),
    )
    response = text_response(
        result.text,
        model=model_label,
        usage=usage,
        request=body,
        function_calls=[(c.id, c.name, c.arguments) for c in result.pending_tool_calls],
    )

    if not body.stream:
        return response

    # The answer is already complete; the stream renders it as the documented event
    # sequence. See app/openresponses/stream.py for why that is honest rather than
    # decorative, and precisely what it does not give you.
    return StreamingResponse(
        astream_response(response),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
