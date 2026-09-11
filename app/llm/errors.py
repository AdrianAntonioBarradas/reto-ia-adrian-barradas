"""Shared LLM error type, so adapters do not import each other."""

from __future__ import annotations


class LLMError(RuntimeError):
    """Provider call failed. Carries the status so the API layer can map it."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
