"""Pluggable providers. Pick implementations via settings (STT_PROVIDER, LLM_PROVIDER)."""

from __future__ import annotations

from settings import Settings
from providers.base import LLMProvider, STTProvider


def make_stt(settings: Settings) -> STTProvider:
    from providers.stt_stub import StubSTT

    # Future: if settings.stt_provider == "mlx_whisper": return MlxWhisperSTT(...)
    return StubSTT()


def make_llm(settings: Settings) -> LLMProvider:
    """Nebius / NVIDIA / Ollama (OpenAI-compatible) or the offline stub; see providers/llm_presets.py."""
    from providers.llm_presets import build_llm

    return build_llm(settings)


__all__ = ["LLMProvider", "STTProvider", "make_llm", "make_stt"]
