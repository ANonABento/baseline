"""Runtime configuration (pydantic-settings). Values come from env vars or a `.env`
file at the repo root or in backend/. See `.env.example` at the repo root."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- audio / segmentation ---
    sample_rate: int = 16_000
    vad_threshold_db: float = -40.0  # frame RMS (dBFS) above this counts as speech
    vad_min_speech_ms: int = 250
    vad_hangover_ms: int = 500  # trailing silence that ends an utterance
    vad_max_utterance_ms: int = 15_000
    vad_preroll_ms: int = 150

    # --- providers ---
    stt_provider: Literal["stub"] = "stub"  # add "mlx_whisper", "elevenlabs", ... later
    # LLM fraud analyzer. Presets + selection logic: providers/llm_presets.py.
    # auto = nebius if NEBIUS_API_KEY, else nvidia if NVIDIA_API_KEY, else stub. "openai" = legacy alias of nebius.
    llm_provider: Literal["auto", "stub", "openai", "nebius", "nvidia", "ollama"] = "auto"
    nebius_api_key: str = ""
    nvidia_api_key: str = ""
    llm_api_key: str = ""  # optional generic override for whichever preset is selected
    llm_base_url: str = ""  # empty = preset default
    llm_model: str = ""  # empty = preset default (confirm the id in the provider console)
    llm_timeout_s: float = 3.0  # per call; on timeout the fraud detector falls back to keywords
    llm_max_tokens: int = 220
    llm_json_mode: bool = True  # response_format=json_object (auto-disabled if the endpoint rejects it)
    llm_context_utterances: int = 16  # rolling transcript window sent to the LLM
    # In stub STT mode, read `<clip>.txt` next to a replayed WAV as the transcript.
    use_sidecar_transcripts: bool = True

    # --- replay ---
    demo_dir: Path = REPO_ROOT / "data" / "demo"
    replay_speed: float = 1.0  # 1.0 = real time
    replay_chunk_ms: int = 100

    # --- fusion ---
    fire_threshold: float = 0.5  # a signal "fires" when score >= this and confidence >= min_conf
    fire_min_confidence: float = 0.3

    # --- enrolled customer shown on the dashboard (placeholder) ---
    customer_name: str = "Margaret Chen"
    customer_id: str = "CUST-004217"

    def resolved_llm_provider(self) -> str:
        """Returns nebius, nvidia, ollama or stub: what make_llm will actually build."""
        from providers.llm_presets import resolve_provider_name

        return resolve_provider_name(self)


@lru_cache
def get_settings() -> Settings:
    return Settings()
