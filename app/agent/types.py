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
class AgentAnswer:
    text: str
    evidence: tuple[EvidenceRef, ...] = ()
    tool_calls_made: tuple[str, ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    # Set when the policy gate answered without consulting the model at all.
    short_circuited: str | None = None
