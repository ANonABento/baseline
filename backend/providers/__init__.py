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
    """Nebius / NVIDIA / Ollama (OpenAI-compatible) or the offline stub; see providers/llm_presets.py."""
    from providers.llm_presets import build_llm

    return build_llm(settings)


__all__ = ["LLMProvider", "STTProvider", "make_llm", "make_stt"]
