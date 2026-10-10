# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["kokoro>=0.9.4", "soundfile", "fastapi", "uvicorn", "numpy", "pip", "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"]
# ///
"""Kokoro TTS server for the 5090 (the AI caller's voice runs locally, not on ElevenLabs).

    uv run gpu/tts_server.py            # binds 127.0.0.1:8880; reach it through an SSH tunnel

POST /tts {"text": "...", "voice": "am_michael"} -> 16 kHz mono int16 PCM (audio/pcm)
GET  /voices -> [{id, label}]"""

from __future__ import annotations

import os

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

VOICES = [
    {"id": "am_michael", "label": "Michael (Kokoro, US male)"},
    {"id": "am_adam", "label": "Adam (Kokoro, US male)"},
    {"id": "bm_george", "label": "George (Kokoro, UK male)"},
    {"id": "af_heart", "label": "Heart (Kokoro, US female)"},
    {"id": "bf_emma", "label": "Emma (Kokoro, UK female)"},
]
SR_IN, SR_OUT = 24_000, 16_000

app = FastAPI()
_pipes: dict[str, object] = {}


def pipe(lang: str):
    from kokoro import KPipeline

    if lang not in _pipes:
        _pipes[lang] = KPipeline(lang_code=lang, device=os.environ.get("KOKORO_DEVICE", "cuda"))
    return _pipes[lang]


class Req(BaseModel):
    text: str
    voice: str = "am_michael"
    speed: float = 1.0


def to_pcm16(x: np.ndarray) -> bytes:
    n = int(round(len(x) * SR_OUT / SR_IN))
    y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x) if len(x) else x
    return (np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()


@app.get("/voices")
def voices():
    return VOICES


@app.post("/tts")
def tts(req: Req):
    text = req.text.strip()[:600]
    if not text:
        raise HTTPException(400, "empty text")
    voice = req.voice if any(v["id"] == req.voice for v in VOICES) else VOICES[0]["id"]
    chunks = [np.asarray(r.audio, dtype=np.float32) for r in pipe(voice[0])(text, voice=voice, speed=req.speed)
              if r.audio is not None]
    audio = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
    return Response(to_pcm16(audio), media_type="audio/pcm")


if __name__ == "__main__":
    for lang in ("a", "b"):  # warm both accents so the first call is fast
        list(pipe(lang)("Hello.", voice="am_michael" if lang == "a" else "bm_george"))
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8880")))
