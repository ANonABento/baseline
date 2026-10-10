"""LLM provider presets, selected by env (LLM_PROVIDER):

    auto    (default) nebius if NEBIUS_API_KEY is set, else nvidia if NVIDIA_API_KEY, else stub
    nebius  Nebius Token Factory (OpenAI-compatible)       key: NEBIUS_API_KEY
    nvidia  NVIDIA API catalog, build.nvidia.com           key: NVIDIA_API_KEY
    ollama  local Ollama OpenAI-compatible endpoint        no key
    openai  legacy alias of nebius
    stub    deterministic offline keyword stub

LLM_BASE_URL / LLM_MODEL / LLM_API_KEY override the preset when non-empty.
NOTE: default base URLs and model ids below are best guesses and must be confirmed against
the provider console before the demo (the detector falls back to keywords if they are wrong)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from providers.base import LLMProvider

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Preset:
    base_url: str
    model: str
    key_setting: str | None  # Settings attribute holding the API key (None = no key needed)


PRESETS: dict[str, Preset] = {
    # Token Factory is the rebrand of Nebius AI Studio; legacy URL: https://api.studio.nebius.com/v1/
    "nebius": Preset("https://api.tokenfactory.nebius.com/v1/", "Qwen/Qwen3-30B-A3B-Instruct-2507", "nebius_api_key"),
    "nvidia": Preset("https://integrate.api.nvidia.com/v1", "nvidia/nemotron-3.5-lightning-30b-a3b", "nvidia_api_key"),
    "ollama": Preset("http://localhost:11434/v1", "qwen3.5:4b", None),
}


@dataclass(frozen=True)
class LLMConfig:
    provider: str  # "nebius" | "nvidia" | "ollama" | "stub"
    base_url: str = ""
    model: str = ""
    api_key: str = ""


def resolve_provider_name(settings) -> str:
    """Which provider will actually be used (keys considered). Mirrors Settings.resolved_llm_provider."""
    choice = (getattr(settings, "llm_provider", "auto") or "auto").lower()
    generic = getattr(settings, "llm_api_key", "")
    if choice == "openai":
        choice = "nebius"
    if choice == "auto":
        if getattr(settings, "nebius_api_key", ""):
            return "nebius"
        if getattr(settings, "nvidia_api_key", ""):
            return "nvidia"
        return "stub"
    if choice not in PRESETS:
        return "stub"
    preset = PRESETS[choice]
    if preset.key_setting and not (generic or getattr(settings, preset.key_setting, "")):
        log.warning("LLM_PROVIDER=%s but no API key set; using the offline stub", choice)
        return "stub"
    return choice


def resolve_llm_config(settings) -> LLMConfig:
    name = resolve_provider_name(settings)
    if name == "stub":
        return LLMConfig("stub")
    preset = PRESETS[name]
    key = getattr(settings, "llm_api_key", "") or (getattr(settings, preset.key_setting, "") if preset.key_setting else "")
    return LLMConfig(
        provider=name,
        base_url=getattr(settings, "llm_base_url", "") or preset.base_url,
        model=getattr(settings, "llm_model", "") or preset.model,
        api_key=key or ("ollama" if name == "ollama" else ""),
    )


def build_llm(settings, http_client=None) -> LLMProvider:
    cfg = resolve_llm_config(settings)
    if cfg.provider == "stub":
        from providers.llm_stub import StubLLM

        return StubLLM()
    from providers.llm_openai import OpenAICompatLLM

    return OpenAICompatLLM(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        timeout_s=float(getattr(settings, "llm_timeout_s", 3.0)),
        max_tokens=int(getattr(settings, "llm_max_tokens", 220)),
        json_mode=bool(getattr(settings, "llm_json_mode", True)),
        provider=cfg.provider,
        http_client=http_client,
    )
