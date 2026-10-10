"""Text-to-speech for the AI side of a live call. Every provider yields 16 kHz mono int16 PCM.

    ElevenLabsTTS  streaming HTTP (ELEVENLABS_API_KEY), `output_format=pcm_16000`, low-latency
                   model (ELEVENLABS_MODEL, default eleven_flash_v2_5)
    MacSayTTS      macOS `say -v <voice>` rendered straight to 16 kHz LEI16 WAV (no network)
    StubTTS        deterministic tone bursts sized to the text (tests / non-mac without a key)

`make_tts(settings)` auto-selects: elevenlabs if a key is set, else say if the binary exists,
else stub (TTS_PROVIDER forces one). ElevenLabs falls back to `say` per utterance on errors.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

SR = 16_000

# macOS voices that exist on a stock install. "Samantha" is the voice CUST-004217's demo
# voiceprint was enrolled from (`make enroll-demo`), i.e. a perfect "clone" of Margaret.
SAY_VOICES: list[dict] = [
    {"id": "Samantha", "label": "Samantha (US, matches Margaret's enrolled voice)"},
    {"id": "Karen", "label": "Karen (Australian)"},
    {"id": "Moira", "label": "Moira (Irish)"},
    {"id": "Daniel", "label": "Daniel (British, male)"},
    {"id": "Kathy", "label": "Kathy (US)"},
    {"id": "Fred", "label": "Fred (US, male, robotic)"},
]

# ElevenLabs premade voices (public library ids). ELEVENLABS_VOICE_ID, if set, is listed first.
ELEVEN_VOICES: list[dict] = [
    {"id": "21m00Tcm4TlvDq8ikWAM", "label": "Rachel (ElevenLabs)"},
    {"id": "EXAVITQu4vr4xnPhcfhC", "label": "Sarah (ElevenLabs)"},
    {"id": "XrExE9yKIg1WjnnlVkGX", "label": "Matilda (ElevenLabs)"},
    {"id": "pNInz6obpgDQGcFmaJgB", "label": "Adam (ElevenLabs, male)"},
]


class TTSProvider(ABC):
    name: str = "base"
    sample_rate: int = SR

    @abstractmethod
    def voices(self) -> list[dict]:
        """[{id, label}] the lobby can offer."""

    @abstractmethod
    def stream(self, text: str, voice: str) -> AsyncIterator[bytes]:
        """Yield int16 LE mono PCM at 16 kHz (any chunk size, even byte count)."""

    def default_voice(self) -> str:
        return self.voices()[0]["id"]

    def valid_voice(self, voice: str) -> bool:
        return any(v["id"] == voice for v in self.voices())

    async def synthesize(self, text: str, voice: str) -> bytes:
        return b"".join([c async for c in self.stream(text, voice)])


# --------------------------------------------------------------------------- stub

class StubTTS(TTSProvider):
    """Tone bursts: `seconds_per_word` of a 220 Hz tone with a little envelope per word."""

    name = "stub"

    def __init__(self, seconds_per_word: float = 0.05, max_seconds: float = 1.0):
        self.seconds_per_word = seconds_per_word
        self.max_seconds = max_seconds

    def voices(self) -> list[dict]:
        return [{"id": "stub-a", "label": "Stub voice A"}, {"id": "stub-b", "label": "Stub voice B"}]

    async def stream(self, text: str, voice: str) -> AsyncIterator[bytes]:
        n_words = max(1, len(text.split()))
        dur = min(self.max_seconds, n_words * self.seconds_per_word)
        t = np.arange(int(SR * dur)) / SR
        x = 0.3 * np.sin(2 * np.pi * (220 if voice != "stub-b" else 180) * t) * np.hanning(len(t))
        pcm = (x * 32767).astype("<i2").tobytes()
        step = SR // 10 * 2
        for i in range(0, len(pcm), step):
            yield pcm[i:i + step]
            await asyncio.sleep(0)


# --------------------------------------------------------------------------- macOS say

class MacSayTTS(TTSProvider):
    name = "say"

    def __init__(self, binary: str = "say"):
        self.binary = shutil.which(binary) or binary
        self._installed: set[str] | None = None

    def voices(self) -> list[dict]:
        return SAY_VOICES

    async def stream(self, text: str, voice: str) -> AsyncIterator[bytes]:
        import soundfile as sf

        voice = voice if self.valid_voice(voice) else self.default_voice()
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="baseline_say_")
        os.close(fd)
        try:
            proc = await asyncio.create_subprocess_exec(
                self.binary, "-v", voice, "-o", path, "--file-format=WAVE", "--data-format=LEI16@16000", "--", text,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"say failed ({proc.returncode}): {err.decode(errors='ignore')[:200]}")
            audio, sr = sf.read(path, dtype="int16", always_2d=True)
        finally:
            Path(path).unlink(missing_ok=True)
        mono = audio[:, 0]
        if sr != SR:
            mono = _resample_int16(mono, sr, SR)
        pcm = mono.astype("<i2").tobytes()
        step = SR // 10 * 2  # 100 ms
        for i in range(0, len(pcm), step):
            yield pcm[i:i + step]


# --------------------------------------------------------------------------- ElevenLabs

class ElevenLabsTTS(TTSProvider):
    name = "elevenlabs"
    URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"

    def __init__(self, api_key: str, voice_id: str = "", model: str = "eleven_flash_v2_5",
                 fallback: TTSProvider | None = None, timeout_s: float = 15.0):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.fallback = fallback
        self.timeout_s = timeout_s
        self._client = None

    def voices(self) -> list[dict]:
        own = [{"id": self.voice_id, "label": "Cloned customer voice (ElevenLabs)"}] if self.voice_id else []
        return own + [v for v in ELEVEN_VOICES if v["id"] != self.voice_id]

    def _http(self):
        import httpx

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_s, connect=5.0))
        return self._client

    async def stream(self, text: str, voice: str) -> AsyncIterator[bytes]:
        voice = voice if self.valid_voice(voice) else self.default_voice()
        sent_any = False
        try:
            async with self._http().stream(
                "POST", self.URL.format(voice=voice),
                params={"output_format": "pcm_16000", "optimize_streaming_latency": "3"},
                headers={"xi-api-key": self.api_key, "accept": "audio/pcm"},
                json={"text": text, "model_id": self.model},
            ) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode(errors="ignore")[:200]
                    raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {body}")
                carry = b""
                async for chunk in r.aiter_bytes():
                    chunk = carry + chunk
                    cut = len(chunk) - (len(chunk) % 2)
                    carry = chunk[cut:]
                    if cut:
                        sent_any = True
                        yield chunk[:cut]
        except Exception as e:
            if sent_any or self.fallback is None:
                raise
            log.warning("ElevenLabs TTS failed (%s); falling back to %s for this line", e, self.fallback.name)
            async for c in self.fallback.stream(text, ""):
                yield c


# --------------------------------------------------------------------------- factory

def _resample_int16(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    f = x.astype(np.float32) / 32768.0
    n_out = int(round(len(f) * sr_out / sr_in))
    y = np.interp(np.linspace(0, len(f) - 1, n_out), np.arange(len(f)), f) if len(f) else f
    return (np.clip(y, -1, 1) * 32767).astype(np.int16)


def say_available() -> bool:
    return shutil.which("say") is not None


def make_tts(settings) -> TTSProvider:
    choice = getattr(settings, "tts_provider", "auto")
    key = getattr(settings, "elevenlabs_api_key", "")
    if choice == "stub":
        return StubTTS()
    say = MacSayTTS() if say_available() else None
    if choice in ("auto", "elevenlabs") and key:
        return ElevenLabsTTS(key, getattr(settings, "elevenlabs_voice_id", ""),
                             getattr(settings, "elevenlabs_model", "eleven_flash_v2_5"), fallback=say)
    if choice == "elevenlabs":
        log.warning("TTS_PROVIDER=elevenlabs but ELEVENLABS_API_KEY is empty; falling back")
    if say is not None:
        return say
    if choice == "say":
        log.warning("TTS_PROVIDER=say but the `say` binary was not found; using stub tones")
    return StubTTS()
