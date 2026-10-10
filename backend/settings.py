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
    # energy = dependency-free RMS placeholder; silero = silero-vad (needs the `ml` extra)
    vad_provider: Literal["energy", "silero"] = "energy"
    silero_threshold: float = 0.5  # speech prob to START speech; speech ENDS below threshold - 0.15

    # --- providers ---
    # stub = placeholder / sidecar transcripts; mlx = mlx-whisper on Apple GPU (needs the `ml` extra).
    # Any real provider that fails to import/load falls back to its stub with a warning.
    stt_provider: Literal["stub", "mlx"] = "stub"
    stt_model: str = "mlx-community/whisper-large-v3-turbo"  # or mlx-community/whisper-small-mlx (~2x faster)
    stt_language: str = "en"
    stt_min_audio_s: float = 0.3  # shorter utterances are not sent to Whisper
    # LLM fraud analyzer. Presets + selection logic: providers/llm_presets.py.
    # auto = nebius if NEBIUS_API_KEY, else nvidia if NVIDIA_API_KEY, else stub. "openai" = legacy alias of nebius.
    llm_provider: Literal["auto", "stub", "openai", "nebius", "nvidia", "ollama"] = "auto"
    nebius_api_key: str = ""
    nvidia_api_key: str = ""
    llm_api_key: str = ""  # optional generic override for whichever preset is selected
    llm_base_url: str = ""  # empty = preset default
    llm_model: str = ""  # empty = preset default (confirm the id in the provider console)
    llm_timeout_s: float = 2.0  # per call; on timeout the fraud detector falls back to keywords
    llm_max_tokens: int = 220
    llm_reasoning_effort: str = ""  # empty = preset default (nebius gpt-oss: low, ollama: none)
    llm_json_mode: bool = True  # response_format=json_object (auto-disabled if the endpoint rejects it)
    llm_context_utterances: int = 16  # rolling transcript window sent to the LLM
    # In stub STT mode, read `<clip>.txt` next to a replayed WAV as the transcript.
    use_sidecar_transcripts: bool = True

    # --- speaker verification (ECAPA vs enrolled voiceprint) ---
    speaker_provider: Literal["stub", "ecapa"] = "stub"
    speaker_model: str = "speechbrain/spkrec-ecapa-voxceleb"
    speaker_device: str = "cpu"
    enroll_dir: Path = REPO_ROOT / "data" / "enroll"
    # Cosine similarity -> risk mapping (logistic through the midpoint of the two anchors):
    #   sim >= speaker_accept_sim  -> risk <= 0.10 (voice matches the enrolled customer)
    #   sim <= speaker_reject_sim  -> risk >= 0.90 (different speaker)
    # Measured per utterance (3-5 s) vs a 26 s enrollment, macOS `say` voices: same voice 0.81-0.88,
    # different voice (Moira vs Samantha) 0.19-0.30. ECAPA's VoxCeleb EER threshold is ~0.25-0.30.
    # Recalibrate on real recordings over the demo channel (genuine same-speaker scores drop to ~0.5-0.7).
    speaker_accept_sim: float = 0.55
    speaker_reject_sim: float = 0.30
    speaker_min_audio_s: float = 1.0  # shorter utterances get confidence 0 (no opinion)
    speaker_max_confidence: float = 0.8

    # --- spoof / synthetic-speech detection ---
    # stub | pretrained (mo-thecreator/Deepfake-audio-detection) | wavlm (our LR on frozen WavLM)
    spoof_provider: Literal["stub", "pretrained", "wavlm"] = "stub"
    spoof_pretrained_model: str = "mo-thecreator/Deepfake-audio-detection"
    spoof_device: str = "auto"  # auto = mps if available else cpu
    spoof_window_s: float = 4.0  # pretrained model window; wavlm uses the window stored in the model file
    spoof_hop_s: float = 2.0
    spoof_min_audio_s: float = 1.0
    spoof_max_confidence: float = 0.7  # unproven on modern clones: never fully trusted
    spoof_lr_path: Path = REPO_ROOT / "models" / "spoof_lr.joblib"
    wavlm_model: str = "microsoft/wavlm-base-plus"
    # wavlm-base-plus main branch only ships a pickle (.bin); the safetensors live in this HF ref.
    wavlm_safetensors_revision: str = "refs/pr/2"

    # --- model lifecycle ---
    warmup_models: bool = True  # load + run one dummy inference per real model at server start
    pretrained_dir: Path = REPO_ROOT / "models" / "pretrained"  # SpeechBrain savedir (gitignored)

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

    def providers_summary(self) -> dict[str, str]:
        """What each stage is configured to use (eval.py / /health record this)."""
        return {
            "stt": self.stt_provider + (f":{self.stt_model.split('/')[-1]}" if self.stt_provider == "mlx" else ""),
            "vad": self.vad_provider,
            "speaker": self.speaker_provider,
            "spoof": self.spoof_provider,
            "llm": self.resolved_llm_provider(),
        }

    def resolved_llm_provider(self) -> str:
        """Returns nebius, nvidia, ollama or stub: what make_llm will actually build."""
        from providers.llm_presets import resolve_provider_name

        return resolve_provider_name(self)


@lru_cache
def get_settings() -> Settings:
    return Settings()
