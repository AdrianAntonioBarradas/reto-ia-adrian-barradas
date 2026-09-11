"""Application settings.

Two conventions carried over from production practice and worth keeping:

* ``environment`` defaults to ``production`` so that a *missing* variable fails
  closed rather than silently enabling development behaviour.
* An empty secret means the feature is disabled, never that it is open. The API
  key check in particular has no development bypass.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RetrievalMode = Literal["context", "structured", "dense", "hybrid"]
LLMProvider = Literal["openai_compatible", "anthropic"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "production"] = "production"

    # --- Public API ---------------------------------------------------------
    # The bearer token the Reto IA platform sends. Empty => every request is
    # refused, in every environment. See app/api/security.py.
    agent_api_key: str = ""
    public_base_url: str = "http://localhost:8000"
    agent_name: str = "Adrián Barradas — Agente de CV"

    # --- LLM ----------------------------------------------------------------
    # Two adapters behind one Protocol. "openai_compatible" covers Google AI Studio,
    # Cerebras, Groq and OpenAI — those differ only by base URL, model and key.
    # Anthropic does not speak that shape, so it gets a native implementation;
    # selecting it is this one variable, and nothing above app/llm/ changes.
    llm_provider: LLMProvider = "openai_compatible"
    # Ignored when llm_provider is "anthropic" — the SDK knows its own endpoint.
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    llm_api_key: str = ""
    llm_model: str = "gemini-3.5-flash"
    llm_max_output_tokens: int = 1024
    llm_temperature: float = 0.2
    llm_timeout_s: float = 45.0
    # Anthropic only: thinking depth. A grounded CV answer is not a hard
    # reasoning task, so "low" keeps latency and cost down without turning
    # thinking off, which has its own failure modes on current models.
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"

    # --- Embeddings ---------------------------------------------------------
    # Local ONNX. No API key, deterministic, and the same encoder family whose
    # thresholds were calibrated on Spanish text in prior work.
    embeddings_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embeddings_dim: int = 384
    # Inside the app directory so the model is baked into the built image at
    # build time rather than downloaded on the first request.
    embeddings_cache_dir: str = ".fastembed_cache"
    # onnxruntime allocates a memory arena per intra-op thread. One is plenty for
    # a 135-vector index and keeps the container inside a 1 GB limit.
    embeddings_threads: int = Field(default=1, ge=1, le=8)

    # --- Retrieval ----------------------------------------------------------
    # The ladder switch: one pipeline, four modes, one evaluation set.
    retrieval_mode: RetrievalMode = "hybrid"
    retrieval_top_k: int = Field(default=6, ge=1, le=20)
    retrieval_candidates: int = Field(default=20, ge=1, le=100)

    # --- Ceilings -----------------------------------------------------------
    max_tool_iterations: int = Field(default=6, ge=1, le=12)
    rate_limit_per_minute: int = Field(default=30, ge=1)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached so importing a module never triggers environment reads twice."""
    return Settings()
