"""The embeddings seam.

Documents and queries are embedded through *separate* methods on purpose. Several
encoder families (the e5 line most notably) require different prefixes for the two
roles, and getting that wrong degrades retrieval silently rather than loudly. Making
the distinction part of the interface means a future encoder swap cannot forget it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...
