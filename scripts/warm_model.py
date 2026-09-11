"""Download the embedding model at build time.

Without this the first request after a cold start pays ~220 MB of download, and a
network problem surfaces as a timeout for a real user rather than as a failed build.
Run from the image build so the weights are baked in.

    uv run python -m scripts.warm_model
"""

from __future__ import annotations

import sys
import time


def main() -> int:
    from app.config import get_settings
    from app.embeddings.local_onnx import LocalOnnxEmbedder

    settings = get_settings()
    started = time.time()
    embedder = LocalOnnxEmbedder(
        settings.embeddings_model,
        expected_dim=settings.embeddings_dim,
        cache_dir=settings.embeddings_cache_dir,
    )
    # Embed once: downloading the files is not the same as the session loading.
    vector = embedder.embed_query("prueba de calentamiento")
    print(
        f"warmed {embedder.model_name} "
        f"({embedder.dimension}d, vector len {len(vector)}) "
        f"in {time.time() - started:.1f}s -> {settings.embeddings_cache_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
