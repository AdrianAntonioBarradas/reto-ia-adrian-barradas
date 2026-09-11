"""Local ONNX embeddings via fastembed.

Chosen over a hosted embeddings API for three reasons worth defending:

1. No third API key, and no per-query cost or network hop on the read path.
2. Deterministic: the same text yields the same vector across runs, which is what
   makes the retrieval evaluation reproducible rather than merely repeatable.
3. ``paraphrase-multilingual-MiniLM-L12-v2`` is the same encoder whose retrieval
   thresholds were previously calibrated against Spanish-language content, so the
   threshold work carries over instead of starting from a guess.

The cost is a ~220 MB model that must be present in the image. `scripts/warm_model.py`
downloads it into ``EMBEDDINGS_CACHE_DIR`` during the build, so a cold container never
pays for it and the first request is not the one that discovers the network is down.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.config import Settings, get_settings


class LocalOnnxEmbedder:
    def __init__(
        self,
        model_name: str,
        *,
        expected_dim: int | None = None,
        cache_dir: str | None = None,
        threads: int | None = None,
    ) -> None:
        # Imported lazily: fastembed pulls in onnxruntime, and modules that only
        # need the type should not pay that import cost.
        from fastembed import TextEmbedding

        self._model_name = model_name
        # threads=1 is a memory decision, not a speed one. onnxruntime allocates a
        # memory arena per intra-op thread; on a 1 GB container the default (one per
        # vCPU) was enough to get the process OOM-killed. Searching 135 vectors does
        # not need parallelism — it takes 4 ms single-threaded.
        self._model = TextEmbedding(model_name, cache_dir=cache_dir, threads=threads)
        self._dimension = self._resolve_dimension(model_name)
        if expected_dim is not None and expected_dim != self._dimension:
            raise ValueError(
                f"EMBEDDINGS_DIM is {expected_dim} but {model_name} produces "
                f"{self._dimension}. A mismatch here corrupts the index silently."
            )

    @staticmethod
    def _resolve_dimension(model_name: str) -> int:
        from fastembed import TextEmbedding

        for spec in TextEmbedding.list_supported_models():
            if spec["model"] == model_name:
                return int(spec["dim"])
        raise ValueError(f"unknown embedding model: {model_name}")

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.embed(list(texts))
        return [[float(x) for x in vector] for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        # query_embed applies the encoder's query-side treatment where it has one.
        vector = next(iter(self._model.query_embed([text])))
        return [float(x) for x in vector]


_embedder: LocalOnnxEmbedder | None = None


def build_embedder(settings: Settings | None = None) -> LocalOnnxEmbedder:
    """Process-wide singleton: loading the ONNX session takes seconds."""
    global _embedder
    if _embedder is None:
        cfg = settings or get_settings()
        _embedder = LocalOnnxEmbedder(
            cfg.embeddings_model,
            expected_dim=cfg.embeddings_dim,
            cache_dir=cfg.embeddings_cache_dir,
            threads=cfg.embeddings_threads,
        )
    return _embedder
