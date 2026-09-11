"""Typed, read-only tools.

The model never sees SQL, a file path, or a raw index. It requests a named tool with
validated arguments; application code decides what that means and returns a
constrained result. That is the least-privilege boundary, and it is the reason this
agent cannot be talked into doing anything other than reading a CV: there is nothing
else to call.

Every tool is a pure read over the in-memory corpus. No writes, no shell, no network,
no filesystem.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.llm.base import ToolSpec


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool hands back.

    ``evidence_ids`` is separate from ``data`` so the answer can be traced to its
    sources without parsing the payload.
    """

    data: dict[str, Any]
    evidence_ids: tuple[str, ...] = ()


ToolHandler = Callable[..., ToolResult]


@dataclass(frozen=True, slots=True)
class Tool:
    spec: ToolSpec
    handler: ToolHandler

    @property
    def name(self) -> str:
        return self.spec.name
