"""Dense retrieval over an in-memory cosine index.

Fifty-two chunks. A brute-force cosine over a 52x384 matrix is a fraction of a
millisecond, exact rather than approximate, and has no index build, no ANN
parameters to tune and no recall cliff to discover in production.

pgvector with HNSW earns its place when the corpus outgrows memory, when several
processes must share an index, or when vectors need to survive a restart. A CV is
none of those: it is small, static, single-tenant and ships inside the repository.
Adding a database here would be complexity that answers no question — see
docs/DECISIONS.md. The ``Retriever`` seam means changing that later is one class.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.embeddings.base import Embedder


@dataclass(frozen=True, slots=True)
class DenseHit:
    chunk_id: str
    score: float


class DenseIndex:
    def __init__(self, documents: dict[str, str], embedder: Embedder) -> None:
        self._ids: list[str] = list(documents)
        self._embedder = embedder
        if self._ids:
            matrix = np.asarray(
                embedder.embed_documents([documents[i] for i in self._ids]), dtype=np.float32
            )
            # Pre-normalise once so search is a single matrix product.
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            self._matrix = matrix / np.clip(norms, 1e-12, None)
        else:
            self._matrix = np.zeros((0, embedder.dimension), dtype=np.float32)

    @property
    def size(self) -> int:
        return len(self._ids)

    def search(self, query: str, top_k: int) -> list[DenseHit]:
        if not self._ids:
            return []
        vector = np.asarray(self._embedder.embed_query(query), dtype=np.float32)
        vector /= max(float(np.linalg.norm(vector)), 1e-12)
        scores = self._matrix @ vector
        # Sort by score then by id: identical scores must not reorder between runs,
        # or the evaluation stops being reproducible.
        order = sorted(range(len(self._ids)), key=lambda i: (-float(scores[i]), self._ids[i]))
        return [DenseHit(chunk_id=self._ids[i], score=float(scores[i])) for i in order[:top_k]]
