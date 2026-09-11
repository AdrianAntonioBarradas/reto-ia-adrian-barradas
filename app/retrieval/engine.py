"""The retrieval ladder.

One pipeline, four modes, selected by ``RETRIEVAL_MODE``:

===========  =========================================================
context      No retrieval. The whole curated profile goes in the prompt.
             The baseline that says whether retrieval is solving a real
             problem at all — for a corpus this small, that is a genuine
             question and not a rhetorical one.
structured   Typed tool lookups only. Deterministic, no vectors.
dense        Cosine search over chunk embeddings.
hybrid       Dense + BM25, fused with reciprocal rank fusion.
===========  =========================================================

Building these as one switchable pipeline rather than four systems is what makes a
measured comparison affordable: the same eval set runs against each rung and the
only variable is the retrieval step.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import RetrievalMode, Settings, get_settings
from app.embeddings.base import Embedder
from app.knowledge.chunker import Chunk, build_chunks
from app.knowledge.corpus import Corpus, get_corpus
from app.retrieval.dense import DenseIndex
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.lexical import BM25Index


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk: Chunk
    score: float
    # Which retriever(s) surfaced it. Shown in the demo's developer view and
    # logged, so a bad answer can be traced to a retrieval decision.
    retrievers: tuple[str, ...]

    @property
    def source_id(self) -> str:
        return self.chunk.source_id


class RetrievalEngine:
    def __init__(
        self,
        corpus: Corpus,
        embedder: Embedder | None = None,
        *,
        mode: RetrievalMode = "hybrid",
        top_k: int = 6,
        candidates: int = 20,
    ) -> None:
        self._corpus = corpus
        self._mode = mode
        self._top_k = top_k
        self._candidates = candidates
        self._chunks = {c.id: c for c in build_chunks(corpus)}
        texts = {cid: c.embedding_text for cid, c in self._chunks.items()}

        self._lexical = BM25Index(texts)
        # The dense index is only built when a mode needs it: loading the encoder
        # costs seconds, and the context/structured rungs must not pay for it.
        self._dense: DenseIndex | None = None
        if mode in {"dense", "hybrid"}:
            if embedder is None:
                raise ValueError(f"mode {mode!r} requires an embedder")
            self._dense = DenseIndex(texts, embedder)

    @property
    def mode(self) -> RetrievalMode:
        return self._mode

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def all_chunks(self) -> list[Chunk]:
        return list(self._chunks.values())

    def search(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        limit = top_k or self._top_k
        if self._mode == "context":
            # No ranking: the caller is going to use the whole corpus anyway.
            return []
        if self._mode == "structured":
            return []
        if self._mode == "dense":
            assert self._dense is not None
            hits = self._dense.search(query, limit)
            return [
                RetrievedChunk(self._chunks[h.chunk_id], h.score, ("dense",))
                for h in hits
                if h.chunk_id in self._chunks
            ]

        # hybrid
        assert self._dense is not None
        dense_hits = self._dense.search(query, self._candidates)
        lexical_hits = self._lexical.search(query, self._candidates)
        dense_ids = [h.chunk_id for h in dense_hits]
        lexical_ids = [h.chunk_id for h in lexical_hits]

        dense_set, lexical_set = set(dense_ids), set(lexical_ids)
        fused = reciprocal_rank_fusion([dense_ids, lexical_ids])

        results: list[RetrievedChunk] = []
        for chunk_id, score in fused[:limit]:
            chunk = self._chunks.get(chunk_id)
            if chunk is None:
                continue
            retrievers = tuple(
                name
                for name, member in (
                    ("dense", chunk_id in dense_set),
                    ("lexical", chunk_id in lexical_set),
                )
                if member
            )
            results.append(RetrievedChunk(chunk, score, retrievers))
        return results


_engine: RetrievalEngine | None = None


def get_engine(settings: Settings | None = None) -> RetrievalEngine:
    """Process-wide singleton.

    Not lru_cache: Settings is a pydantic model and therefore unhashable, and
    building the index loads the encoder, so it must happen exactly once.
    """
    global _engine
    if _engine is not None:
        return _engine
    cfg = settings or get_settings()
    embedder: Embedder | None = None
    if cfg.retrieval_mode in {"dense", "hybrid"}:
        from app.embeddings.local_onnx import build_embedder

        embedder = build_embedder(cfg)
    _engine = RetrievalEngine(
        get_corpus(),
        embedder,
        mode=cfg.retrieval_mode,
        top_k=cfg.retrieval_top_k,
        candidates=cfg.retrieval_candidates,
    )
    return _engine
