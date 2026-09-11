"""Server-Sent Events for ``stream: true``.

The agent's LLM call is not itself streamed — the adapter returns a whole turn — so
this emits the specification's event sequence around a completed answer rather than
token by token. That is an honest limitation, not a fake: every event carries real
content, the deltas are real slices of the real answer, and a client that renders
progressively gets progressive text. What it does not get is text arriving as the
model produces it.

Doing it this way keeps one code path for the answer itself. Genuine token streaming
would mean a streaming variant of every adapter and of the tool loop, for a feature
the challenge explicitly does not require.

Every field below comes from the specification's event schemas, which are strict:
``sequence_number`` is required on all of them, and the item/content indices must be
consistent across the lifecycle of one item.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from app.openresponses.schemas import OutputMessage, ResponseObject

# Deltas are cosmetic here, so the size only controls how granular the progressive
# render looks. Small enough to look like typing, large enough not to flood.
DELTA_CHARS = 24


def _sse(payload: dict[str, Any]) -> str:
    """One SSE frame. The event name mirrors the payload type, as clients expect."""
    return f"event: {payload['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chunks(text: str, size: int = DELTA_CHARS) -> Iterator[str]:
    for start in range(0, len(text), size):
        yield text[start : start + size]


def stream_response(response: ResponseObject) -> Iterator[str]:
    """Render a finished response as the documented event sequence."""
    seq = 0

    def nxt() -> int:
        nonlocal seq
        seq += 1
        return seq

    in_progress = response.model_copy(update={"status": "in_progress", "completed_at": None})
    yield _sse(
        {
            "type": "response.created",
            "sequence_number": nxt(),
            "response": in_progress.model_dump(mode="json"),
        }
    )
    yield _sse(
        {
            "type": "response.in_progress",
            "sequence_number": nxt(),
            "response": in_progress.model_dump(mode="json"),
        }
    )

    for output_index, item in enumerate(response.output):
        item_json = item.model_dump(mode="json")
        yield _sse(
            {
                "type": "response.output_item.added",
                "sequence_number": nxt(),
                "output_index": output_index,
                "item": item_json,
            }
        )

        if isinstance(item, OutputMessage):
            for content_index, part in enumerate(item.content):
                part_json = part.model_dump(mode="json")
                # The part is announced empty, filled by deltas, then closed full.
                yield _sse(
                    {
                        "type": "response.content_part.added",
                        "sequence_number": nxt(),
                        "item_id": item.id,
                        "output_index": output_index,
                        "content_index": content_index,
                        "part": {**part_json, "text": ""},
                    }
                )
                for delta in _chunks(part.text):
                    yield _sse(
                        {
                            "type": "response.output_text.delta",
                            "sequence_number": nxt(),
                            "item_id": item.id,
                            "output_index": output_index,
                            "content_index": content_index,
                            "delta": delta,
                        }
                    )
                yield _sse(
                    {
                        "type": "response.output_text.done",
                        "sequence_number": nxt(),
                        "item_id": item.id,
                        "output_index": output_index,
                        "content_index": content_index,
                        "text": part.text,
                    }
                )
                yield _sse(
                    {
                        "type": "response.content_part.done",
                        "sequence_number": nxt(),
                        "item_id": item.id,
                        "output_index": output_index,
                        "content_index": content_index,
                        "part": part_json,
                    }
                )

        yield _sse(
            {
                "type": "response.output_item.done",
                "sequence_number": nxt(),
                "output_index": output_index,
                "item": item_json,
            }
        )

    terminal = "response.failed" if response.status == "failed" else "response.completed"
    yield _sse(
        {"type": terminal, "sequence_number": nxt(), "response": response.model_dump(mode="json")}
    )
    # The sentinel is not an event; parsers skip it but clients rely on it.
    yield "data: [DONE]\n\n"


async def astream_response(response: ResponseObject) -> AsyncIterator[str]:
    for frame in stream_response(response):
        yield frame
