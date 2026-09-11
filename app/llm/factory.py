"""Pick the adapter from configuration.

The whole point of the Protocol: this function is the only place in the codebase
that knows more than one provider exists.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.llm.base import LLMAdapter


def build_llm_adapter(settings: Settings | None = None) -> LLMAdapter:
    cfg = settings or get_settings()
    if cfg.llm_provider == "anthropic":
        from app.llm.anthropic_native import build_anthropic_adapter

        return build_anthropic_adapter(cfg)

    from app.llm.openai_compatible import build_llm_adapter as build_openai_compatible

    return build_openai_compatible(cfg)
