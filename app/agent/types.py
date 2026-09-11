"""What the agent hands back to the API layer.

Deliberately not an Open Responses type: the agent must stay ignorant of the
protocol it is being served behind.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Where a claim came from. Carried into telemetry, and shown in the demo."""

    source_id: str
    kind: str
    score: float | None = None


@dataclass(frozen=True, slots=True)
class PendingToolCall:
    """A tool the *caller* declared, which the caller must execute.

    Open Responses lets a client pass its own ``tools``. Those are not ours to run —
    we surface the model's request as a ``function_call`` output item and the client
    supplies the result on the next turn. Distinct from the agent's own four tools,
    which execute server-side inside the loop.
    """

    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class AgentAnswer:
    text: str
    evidence: tuple[EvidenceRef, ...] = ()
    tool_calls_made: tuple[str, ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    # Set when the policy gate answered without consulting the model at all.
    short_circuited: str | None = None
    # Tool calls for client-declared tools, returned rather than executed.
    pending_tool_calls: tuple[PendingToolCall, ...] = ()
