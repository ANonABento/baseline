"""Ingest -> segmenter (VAD) -> per-utterance fan-out to detectors -> fusion -> events.

One `CallPipeline` per call/WebSocket session. Live mic frames and replayed WAVs both go
through `feed_pcm16` / `feed_float`, so replay exercises exactly the live path.

Per utterance (processed in order by a single worker so the rolling transcript is ordered):
  1. STT and every audio detector (speaker, spoof, prosody) start concurrently.
  2. When STT returns, a `transcript` event is emitted and text detectors (fraud) start.
  3. Each detector emits its `signal` event as soon as it finishes.
  4. After all finish: fusion emits `trust` and (if changed) `alert`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from core import CallContext, Utterance
from detectors.base import Detector
from detectors.fraud import FraudDetector
from detectors.prosody import ProsodyDetector
from detectors.speaker import make_speaker_detector
from detectors.spoof import make_spoof_detector
from events import AlertEvent, DetectorResult, Event, SignalEvent, StatusEvent, TranscriptEvent
from fusion import Fusion
from providers import make_llm, make_stt
from providers.base import STTProvider
from providers.stt_stub import SidecarTranscriptSTT, sidecar_path_for
from segmenter import Segment, Segmenter, make_segmenter
from settings import Settings, get_settings

log = logging.getLogger(__name__)

EmitFn = Callable[[Event], Awaitable[None]]
_SENTINEL = object()


# ---------------------------------------------------------------- audio helpers

def pcm16_to_float(data: bytes) -> np.ndarray:
    if len(data) % 2:
        data = data[:-1]
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def load_wav(path: Path, target_sr: int = 16_000) -> np.ndarray:
    """Load any soundfile-readable audio as float32 mono at target_sr (polyphase resampling
    with scipy when the ml extra is installed, linear interpolation otherwise)."""
    from ml.audio import read_audio

    return read_audio(path, target_sr)


def load_clip_sidecars(wav: Path) -> tuple[list[str] | None, dict]:
    """Sidecar transcript (`<clip>.txt`) lines and stub hints (`<clip>.meta.json`)."""
    txt = sidecar_path_for(wav)
    lines = txt.read_text(encoding="utf-8").splitlines() if txt.exists() else None
    meta_p = wav.with_suffix(".meta.json")
    hints: dict = {}
    if meta_p.exists():
        try:
            hints = json.loads(meta_p.read_text(encoding="utf-8")).get("stub_hints", {}) or {}
        except (json.JSONDecodeError, AttributeError):
            log.warning("Bad meta sidecar %s", meta_p)
    return lines, hints


# ---------------------------------------------------------------- pipeline

def default_detectors(settings: Settings) -> list[Detector]:
    return [make_speaker_detector(settings), make_spoof_detector(settings), ProsodyDetector(),
            FraudDetector(make_llm(settings), timeout_s=settings.llm_timeout_s)]


def warmup_models(settings: Settings | None = None) -> dict[str, float]:
    """Blocking: load every configured real model and run one dummy inference (MPS/MLX first
    inference is ~1 s, so do it before the first call). Returns seconds per component
    (-1 = failed; it is retried lazily on first use). Each model warms up on its own
    executor thread, so they load in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    settings = settings or get_settings()
    jobs: dict[str, Callable[[], None]] = {}
    stt = make_stt(settings)
    if hasattr(stt, "warmup"):
        jobs[f"stt:{stt.name}"] = stt.warmup
    for d in default_detectors(settings):
        if hasattr(d, "warmup"):
            jobs[f"{d.name}:{type(d).__name__}"] = d.warmup
    if settings.vad_provider == "silero":
        def _vad() -> None:
            seg = make_segmenter(settings)
            seg.feed(np.zeros(settings.sample_rate, dtype=np.float32))
            seg.reset()
        jobs["vad:silero"] = _vad

    def timed(fn: Callable[[], None]) -> float:
        t = time.perf_counter()
        fn()
        return round(time.perf_counter() - t, 2)

    out: dict[str, float] = {}
    if not jobs:
        return out
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = {k: ex.submit(timed, fn) for k, fn in jobs.items()}
        for k, f in futs.items():
            try:
                out[k] = f.result()
            except Exception:
                log.exception("warmup failed for %s (it will be retried lazily on first use)", k)
                out[k] = -1.0
    return out


class CallPipeline:
    def __init__(self, emit: EmitFn, settings: Settings | None = None, *,
                 stt: STTProvider | None = None, detectors: list[Detector] | None = None,
                 segmenter: Segmenter | None = None, fusion: Fusion | None = None):
        self.settings = settings or get_settings()
        s = self.settings
        self.emit = emit
        self.default_stt = stt or make_stt(s)
        self.stt = self.default_stt
        self.detectors = detectors if detectors is not None else default_detectors(s)
        self.segmenter = segmenter or make_segmenter(s)
        self.fusion = fusion or Fusion(s.fire_threshold, s.fire_min_confidence)
        self.ctx = CallContext()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._next_id = 0
        self.last_alert: AlertEvent | None = None
        self.signal_log: list[SignalEvent] = []
        self.utterance_timings: list[dict] = []

    @property
    def providers(self) -> dict[str, str]:
        """Implementations actually in use (after any fallback to stubs)."""
        by_name = {d.name: type(d).__name__ for d in self.detectors}
        return {"stt": self.default_stt.name, "vad": type(self.segmenter).__name__,
                "speaker": by_name.get("speaker", "-"), "spoof": by_name.get("spoof", "-")}

    # -------------------------------------------------- lifecycle

    def start_call(self, *, customer_id: str = "", stt: STTProvider | None = None,
                   stub_hints: dict | None = None) -> None:
        """Reset all per-call state. Pass `stt` to override (e.g. a sidecar transcript)."""
        self.segmenter.reset()
        self.fusion.reset()
        self.ctx = CallContext(customer_id=customer_id or self.settings.customer_id,
                               stub_hints=stub_hints or {})
        for d in self.detectors:
            d.reset(self.ctx)
        self.stt = stt or self.default_stt
        self._next_id = 0
        self.last_alert = None
        self.signal_log = []
        self.utterance_timings = []
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_worker())

    async def end_call(self) -> None:
        """Flush the segmenter and wait until every queued utterance is fully processed."""
        for seg in self.segmenter.flush():
            self._enqueue(seg)
        self._queue.put_nowait(("finalize", None))
        self._ensure_worker()
        await self._queue.join()

    async def close(self) -> None:
        if self._worker and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    # -------------------------------------------------- ingest

    def feed_pcm16(self, data: bytes) -> None:
        self.feed_float(pcm16_to_float(data))

    def feed_float(self, samples: np.ndarray) -> None:
        for seg in self.segmenter.feed(samples):
            self._enqueue(seg)

    def _enqueue(self, seg: Segment) -> None:
        self._ensure_worker()
        self._queue.put_nowait(("seg", seg))

    # -------------------------------------------------- processing

    async def _run_worker(self) -> None:
        while True:
            kind, item = await self._queue.get()
            try:
                if kind == "seg":
                    await self._process(item.audio, item.t_start, item.t_end)
                elif kind == "finalize":  # end of call: leftover STT text (e.g. sidecar lines) with no audio
                    leftover = self.stt.finalize()
                    if leftover:
                        t = self.ctx.utterances[-1].t_end if self.ctx.utterances else 0.0
                        await self._process(np.zeros(0, dtype=np.float32), t, t, text_override=leftover)
            except Exception:
                log.exception("utterance processing failed")
                await self._safe_emit(StatusEvent(state="error", message="utterance processing failed"))
            finally:
                self._queue.task_done()

    async def _safe_emit(self, ev: Event) -> None:
        try:
            await self.emit(ev)
        except Exception:
            log.debug("emit failed (client gone?)", exc_info=True)

    async def _run_detector(self, det: Detector, utt: Utterance, t0: float) -> None:
        try:
            r = await det.analyze(utt, self.ctx)
        except Exception as e:
            log.exception("detector %s failed", det.name)
            r = DetectorResult(signal=det.name, score=0.0, confidence=0.0, reason=f"detector error: {e}")
        self.fusion.update(r)
        ev = SignalEvent(**r.model_dump(), utterance_id=utt.id, latency_ms=round((time.perf_counter() - t0) * 1000, 1))
        self.signal_log.append(ev)
        await self._safe_emit(ev)

    async def _process(self, audio: np.ndarray, t_start: float, t_end: float, text_override: str | None = None) -> None:
        t0 = time.perf_counter()
        utt = Utterance(id=self._next_id, audio=audio, sample_rate=self.settings.sample_rate,
                        t_start=round(t_start, 2), t_end=round(t_end, 2))
        self._next_id += 1
        has_audio = audio.size > 0
        audio_tasks = [
            asyncio.create_task(self._run_detector(d, utt, t0))
            for d in self.detectors if not d.requires_text and has_audio
        ]
        try:
            utt.text = text_override if text_override is not None else await self.stt.transcribe(utt)
        except Exception:
            log.exception("STT failed")
            utt.text = ""
        stt_ms = round((time.perf_counter() - t0) * 1000, 1)
        self.ctx.utterances.append(utt)
        if utt.text:
            await self._safe_emit(TranscriptEvent(utterance_id=utt.id, t_start=utt.t_start, t_end=utt.t_end,
                                                  text=utt.text, latency_ms=stt_ms))
        text_tasks = [asyncio.create_task(self._run_detector(d, utt, t0)) for d in self.detectors if d.requires_text]
        await asyncio.gather(*audio_tasks, *text_tasks)
        total_ms = round((time.perf_counter() - t0) * 1000, 1)
        timing = {"utterance_id": utt.id, "audio_s": round(utt.duration, 2), "stt_ms": stt_ms, "total_ms": total_ms,
                  **{f"{e.signal}_ms": e.latency_ms for e in self.signal_log if e.utterance_id == utt.id}}
        self.utterance_timings.append(timing)
        log.info("utt %d (%.1fs audio): %s", utt.id, utt.duration,
                 " ".join(f"{k}={v}" for k, v in timing.items() if k.endswith("_ms")))
        await self._safe_emit(self.fusion.trust_event(utt.id))
        alert = self.fusion.alert_if_changed()
        if alert is not None:
            self.last_alert = alert
            await self._safe_emit(alert)


# ---------------------------------------------------------------- offline helper (eval/tests)

@dataclass
class CallResult:
    events: list[Event] = field(default_factory=list)
    alert_level: str = "none"
    trust: float = 100.0
    signals: dict[str, dict] = field(default_factory=dict)  # final fused per-signal state
    fired: list[str] = field(default_factory=list)
    transcript: str = ""
    mean_latency_ms: float = 0.0
    used_sidecar: bool = False
    utterance_timings: list[dict] = field(default_factory=list)  # per utterance: stt_ms, <signal>_ms, total_ms
    providers: dict[str, str] = field(default_factory=dict)


def stt_for_clip(wav: Path, settings: Settings, active_stt: STTProvider | None = None) -> tuple[STTProvider | None, dict]:
    """In stub STT mode (configured, or a real provider that fell back to the stub), use the
    sidecar transcript if present. Returns (stt override, stub hints)."""
    lines, hints = load_clip_sidecars(wav)
    stt = None
    is_stub = (active_stt.name == "stub") if active_stt is not None else settings.stt_provider == "stub"
    if is_stub and settings.use_sidecar_transcripts and lines is not None:
        stt = SidecarTranscriptSTT(lines)
    return stt, hints


async def analyze_wav(path: Path, settings: Settings | None = None, *, chunk_ms: int = 100,
                      use_stub_hints: bool = True, customer_id: str = "") -> CallResult:
    """Run one file through the full pipeline as fast as possible (no real-time pacing).
    eval.py passes use_stub_hints=False so `.meta.json` demo hints never inflate accuracy."""
    settings = settings or get_settings()
    result = CallResult()

    async def collect(ev: Event) -> None:
        result.events.append(ev)

    pipe = CallPipeline(collect, settings)
    stt, hints = stt_for_clip(path, settings, pipe.default_stt)
    pipe.start_call(customer_id=customer_id, stt=stt, stub_hints=hints if use_stub_hints else {})
    audio = load_wav(path, settings.sample_rate)
    step = int(settings.sample_rate * chunk_ms / 1000)
    for i in range(0, len(audio), step):
        pipe.feed_float(audio[i:i + step])
    await pipe.end_call()
    await pipe.close()

    result.alert_level = pipe.fusion.level
    result.trust = pipe.fusion.trust
    result.fired = pipe.fusion.fired()
    result.signals = {k: {"score": round(s.score, 3), "confidence": round(s.confidence, 3), "reason": s.reason}
                      for k, s in pipe.fusion.signals.items()}
    result.transcript = pipe.ctx.transcript
    result.used_sidecar = stt is not None
    lat = [e.latency_ms for e in pipe.signal_log]
    result.mean_latency_ms = round(sum(lat) / len(lat), 1) if lat else 0.0
    result.utterance_timings = pipe.utterance_timings
    result.providers = pipe.providers
    return result
