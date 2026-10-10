"""Pluggable providers. Pick implementations via settings (STT_PROVIDER, LLM_PROVIDER)."""

from __future__ import annotations

from settings import Settings
from providers.base import LLMProvider, STTProvider


def make_stt(settings: Settings) -> STTProvider:
    from providers.stt_stub import StubSTT

    # Future: if settings.stt_provider == "mlx_whisper": return MlxWhisperSTT(...)
    return StubSTT()


def make_llm(settings: Settings) -> LLMProvider:
    if settings.resolved_llm_provider() == "openai" and settings.nebius_api_key:
        from providers.llm_openai import OpenAICompatLLM

        return OpenAICompatLLM(
            api_key=settings.nebius_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_s=settings.llm_timeout_s,
        )
    from providers.llm_stub import StubLLM

    return StubLLM()


__all__ = ["LLMProvider", "STTProvider", "make_llm", "make_stt"]
