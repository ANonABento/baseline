import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# The default test suite is deterministic and model-free: force stub providers even if a
# developer's .env selects real models (env vars beat the .env file in pydantic-settings).
# Real-model tests (tests/test_ml_models.py) build their own Settings and skip without the ml extra.
for _k, _v in {"STT_PROVIDER": "stub", "VAD_PROVIDER": "energy", "SPEAKER_PROVIDER": "stub",
               "SPOOF_PROVIDER": "stub", "WARMUP_MODELS": "false",
               # Never let a developer's real keys/voices from .env leak into tests (or hit the network).
               "NEBIUS_API_KEY": "", "NVIDIA_API_KEY": "", "LLM_API_KEY": "",
               "ELEVENLABS_API_KEY": "", "ELEVENLABS_VOICE_ID": "", "ELEVENLABS_VOICES": ""}.items():
    os.environ[_k] = _v
