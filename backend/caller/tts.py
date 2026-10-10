"""Text-to-speech for the AI side of a live call. Every provider yields 16 kHz mono int16 PCM.

    KokoroTTS      Kokoro-82M on our own GPU box (KOKORO_URL, gpu/tts_server.py): the AI caller's voice
    SplitTTS       caller lines -> Kokoro, Baseline's own voice -> ElevenLabs (scam scripts never leave our GPU)
    ElevenLabsTTS  streaming HTTP (ELEVENLABS_API_KEY), `output_format=pcm_16000`, low-latency
                   model (ELEVENLABS_MODEL, default eleven_flash_v2_5)
    MacSayTTS      macOS `say -v <voice>` rendered straight to 16 kHz LEI16 WAV (no network)
    StubTTS        deterministic tone bursts sized to the text (tests / non-mac without a key)

`make_tts(settings)` auto-selects: kokoro (+ ElevenLabs for Baseline) if KOKORO_URL is set, else elevenlabs if a key is set, else say if the binary exists,
else stub (TTS_PROVIDER forces one). ElevenLabs falls back to `say` per utterance on errors.
"""

from __future__ import annotations

import asyncio
import contextlib
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
# voiceprint was enrolled from (`make enroll-demo`), i.e. a perfect "clone" of the demo voiceprint.
SAY_VOICES: list[dict] = [
    {"id": "Samantha", "label": "Samantha (US, matches the demo voiceprint)"},
    {"id": "Karen", "label": "Karen (Australian)"},
    {"id": "Moira", "label": "Moira (Irish)"},
    {"id": "Daniel", "label": "Daniel (British, male)"},
    {"id": "Kathy", "label": "Kathy (US)"},
    {"id": "Fred", "label": "Fred (US, male, robotic)"},
]

# ElevenLabs premade voices (public library ids) for the AI caller. ELEVENLABS_VOICE_ID, if set, is listed
# first. Baseline's own voice (BASELINE_VOICE_ID, "Sarah") is deliberately not a caller voice.
ELEVEN_VOICES: list[dict] = [
    {"id": "CwhRBWXzGAHq8TQ4Fs17", "label": "Roger (ElevenLabs)"},
    {"id": "N2lVS1w4EtoT3dr4eOWO", "label": "Callum (ElevenLabs)"},
    {"id": "JBFqnCBsd6RMkjVDRZzb", "label": "George (ElevenLabs)"},
    {"id": "XrExE9yKIg1WjnnlVkGX", "label": "Matilda (ElevenLabs)"},
]
STOCK_CALLER_VOICES = ("CwhRBWXzGAHq8TQ4Fs17", "N2lVS1w4EtoT3dr4eOWO", "JBFqnCBsd6RMkjVDRZzb")


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
        return any(v["id"] == voice for v in self.voices()) or voice in getattr(self, "hidden_voices", ())

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
    """`say` costs ~0.85 s per call, mostly process start + voice load before it reads its input.
    We keep one pre-spawned `say -f -` process per voice waiting on stdin (it loads while idle)
    and hand it the text when needed: ~0.45 s to a finished 16 kHz WAV."""

    name = "say"

    def __init__(self, binary: str = "say", prespawn: bool = True):
        self.binary = shutil.which(binary) or binary
        self.prespawn = prespawn
        self._warm: dict[str, tuple[asyncio.subprocess.Process, str]] = {}

    def voices(self) -> list[dict]:
        return SAY_VOICES

    async def _spawn(self, voice: str) -> tuple[asyncio.subprocess.Process, str]:
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="baseline_say_")
        os.close(fd)
        proc = await asyncio.create_subprocess_exec(
            self.binary, "-v", voice, "-o", path, "--file-format=WAVE", "--data-format=LEI16@16000", "-f", "-",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        return proc, path

    async def warm(self, voice: str) -> None:
        if self.prespawn and voice not in self._warm:
            self._warm[voice] = await self._spawn(voice)

    async def close(self) -> None:
        for proc, path in self._warm.values():
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            Path(path).unlink(missing_ok=True)
        self._warm.clear()

    async def stream(self, text: str, voice: str) -> AsyncIterator[bytes]:
        import soundfile as sf

        voice = voice if self.valid_voice(voice) else self.default_voice()
        warm = self._warm.pop(voice, None)
        if warm is not None and warm[0].returncode is not None:  # died while idle
            Path(warm[1]).unlink(missing_ok=True)
            warm = None
        proc, path = warm or await self._spawn(voice)
        try:
            _, err = await proc.communicate(text.replace("\n", " ").encode("utf-8"))
            if self.prespawn:  # next line's process loads while this one plays
                self._warm[voice] = await self._spawn(voice)
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
                 fallback: TTSProvider | None = None, timeout_s: float = 15.0, voices: list[dict] | None = None,
                 own_label: str = "Cloned customer voice (ElevenLabs)", hidden_voices: tuple[str, ...] = ()):
        self.api_key = api_key
        self.hidden_voices = tuple(v for v in hidden_voices if v)  # usable (Baseline's voice) but not offered
        self.voice_id = voice_id
        self.model = model
        self.fallback = fallback
        self.timeout_s = timeout_s
        self._client = None
        if voices:  # ELEVENLABS_VOICES: exactly these, default voice first
            if voice_id and not any(v["id"] == voice_id for v in voices):
                voices = [{"id": voice_id, "label": "Default voice (ElevenLabs)"}] + voices
            voices = sorted(voices, key=lambda v: v["id"] != voice_id)
            # stock caller voices stay available (scenarios that don't impersonate the customer use them)
            self._voices = voices + [v for v in ELEVEN_VOICES if not any(x["id"] == v["id"] for x in voices)]
        else:
            own = [{"id": voice_id, "label": own_label}] if voice_id else []
            self._voices = own + [v for v in ELEVEN_VOICES if v["id"] != voice_id]

    def voices(self) -> list[dict]:
        return self._voices

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


# --------------------------------------------------------------------------- Kokoro (own GPU)

KOKORO_VOICES: list[dict] = [
    {"id": "am_michael", "label": "Michael (Kokoro, US male)"},
    {"id": "am_adam", "label": "Adam (Kokoro, US male)"},
    {"id": "bm_george", "label": "George (Kokoro, UK male)"},
    {"id": "af_heart", "label": "Heart (Kokoro, US female)"},
    {"id": "bf_emma", "label": "Emma (Kokoro, UK female)"},
]


class KokoroTTS(TTSProvider):
    name = "kokoro"

    def __init__(self, url: str, fallback: TTSProvider | None = None, timeout_s: float = 10.0):
        self.url = url.rstrip("/")
        self.fallback = fallback
        self.timeout_s = timeout_s
        self._client = None

    def voices(self) -> list[dict]:
        return KOKORO_VOICES

    async def stream(self, text: str, voice: str) -> AsyncIterator[bytes]:
        import httpx

        voice = voice if self.valid_voice(voice) else self.default_voice()
        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_s, connect=3.0))
            r = await self._client.post(f"{self.url}/tts", json={"text": text, "voice": voice})
            r.raise_for_status()
            pcm = r.content[: len(r.content) - len(r.content) % 2]
        except Exception as e:
            if self.fallback is None:
                raise
            log.warning("Kokoro TTS failed (%s); falling back to %s for this line", e, self.fallback.name)
            async for c in self.fallback.stream(text, ""):
                yield c
            return
        step = SR // 5 * 2  # 200 ms chunks
        for i in range(0, len(pcm), step):
            yield pcm[i:i + step]


class SplitTTS(TTSProvider):
    """Caller voices from `caller`; Baseline's own (hidden) voice from `baseline`."""

    def __init__(self, caller: TTSProvider, baseline: TTSProvider, baseline_voice_id: str):
        self.caller = caller
        self.baseline = baseline
        self.baseline_voice_id = baseline_voice_id
        self.name = caller.name
        self.hidden_voices = (baseline_voice_id,)

    def voices(self) -> list[dict]:
        return self.caller.voices()

    def stream(self, text: str, voice: str) -> AsyncIterator[bytes]:
        if voice == self.baseline_voice_id:
            return self.baseline.stream(text, voice)
        return self.caller.stream(text, voice)


# --------------------------------------------------------------------------- factory

def _resample_int16(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    f = x.astype(np.float32) / 32768.0
    n_out = int(round(len(f) * sr_out / sr_in))
    y = np.interp(np.linspace(0, len(f) - 1, n_out), np.arange(len(f)), f) if len(f) else f
    return (np.clip(y, -1, 1) * 32767).astype(np.int16)


def baseline_voice(tts: TTSProvider, settings) -> str:
    """The voice Baseline itself speaks with (interventions)."""
    if isinstance(tts, SplitTTS):
        return tts.baseline_voice_id
    if tts.name == "elevenlabs":
        return getattr(settings, "baseline_voice_id", "") or tts.default_voice()
    if tts.name == "say":
        v = getattr(settings, "baseline_say_voice", "Samantha")
        return v if tts.valid_voice(v) else tts.default_voice()
    ids = [v["id"] for v in tts.voices()]
    return ids[-1] if ids else ""


def caller_voice(tts: TTSProvider, settings, *, clone: bool, rng=None) -> str:
    """voice=random for the AI caller: the cloned customer voice (ELEVENLABS_VOICE_ID) when the scenario
    impersonates the customer, else a stock voice (never Baseline's own)."""
    import random as _random

    rng = rng or _random
    ids = [v["id"] for v in tts.voices()]
    clone_id = getattr(settings, "elevenlabs_voice_id", "")
    if tts.name == "elevenlabs":
        if clone and clone_id and clone_id in ids:
            return clone_id
        stock = [v for v in STOCK_CALLER_VOICES if v in ids] or [v for v in ids if v != clone_id] or ids
        return rng.choice(stock)
    return rng.choice(ids)


def parse_voice_list(spec: str) -> list[dict]:
    """"Kevin (clone):abc123,Daniel:def456" -> [{id, label}]. Entries without a label use the id."""
    out: list[dict] = []
    for item in (spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        label, sep, vid = item.rpartition(":")
        vid = vid.strip()
        if vid and not any(v["id"] == vid for v in out):
            out.append({"id": vid, "label": (label.strip() if sep and label.strip() else vid)})
    return out


def say_available() -> bool:
    return shutil.which("say") is not None


def make_tts(settings) -> TTSProvider:
    choice = getattr(settings, "tts_provider", "auto")
    key = getattr(settings, "elevenlabs_api_key", "")
    if choice == "stub":
        return StubTTS()
    say = MacSayTTS() if say_available() else None
    kokoro_url = getattr(settings, "kokoro_url", "")
    if choice == "kokoro" or (choice == "auto" and kokoro_url):
        if not kokoro_url:
            log.warning("TTS_PROVIDER=kokoro but KOKORO_URL is empty; falling back")
        else:
            caller = KokoroTTS(kokoro_url, fallback=say)
            if key:
                eleven = ElevenLabsTTS(key, model=getattr(settings, "elevenlabs_model", "eleven_flash_v2_5"),
                                       fallback=say)
                return SplitTTS(caller, eleven, getattr(settings, "baseline_voice_id", ""))
            return caller
    if choice in ("auto", "elevenlabs") and key:
        return ElevenLabsTTS(key, getattr(settings, "elevenlabs_voice_id", ""),
                             getattr(settings, "elevenlabs_model", "eleven_flash_v2_5"), fallback=say,
                             voices=parse_voice_list(getattr(settings, "elevenlabs_voices", "")),
                             own_label=f"{getattr(settings, 'customer_name', 'Customer')} (cloned voice)",
                             hidden_voices=(getattr(settings, "baseline_voice_id", ""),))
    if choice == "elevenlabs":
        log.warning("TTS_PROVIDER=elevenlabs but ELEVENLABS_API_KEY is empty; falling back")
    if say is not None:
        return say
    if choice == "say":
        log.warning("TTS_PROVIDER=say but the `say` binary was not found; using stub tones")
    return StubTTS()
