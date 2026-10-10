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
    llm_provider: Literal["auto", "stub", "openai"] = "auto"  # auto = openai if key present
    nebius_api_key: str = ""
    llm_base_url: str = "https://api.studio.nebius.com/v1/"
    llm_model: str = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    llm_timeout_s: float = 8.0
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
        if self.llm_provider == "auto":
            return "openai" if self.nebius_api_key else "stub"
        return self.llm_provider


@lru_cache
def get_settings() -> Settings:
    return Settings()
