"""Pluggable providers. Pick implementations via settings (STT_PROVIDER, LLM_PROVIDER)."""

from __future__ import annotations

import logging

from settings import Settings
from providers.base import LLMProvider, STTProvider

log = logging.getLogger(__name__)


def make_stt(settings: Settings) -> STTProvider:
    from providers.stt_stub import StubSTT

    if settings.stt_provider == "mlx":
        from ml.runtime import has_modules

        if has_modules("mlx_whisper", "mlx"):
            from providers.stt_mlx import MlxWhisperSTT

            return MlxWhisperSTT(settings.stt_model, settings.stt_language, settings.stt_min_audio_s)
        log.warning("STT_PROVIDER=mlx but mlx-whisper is not installed (uv sync --extra ml); using stub STT")
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
