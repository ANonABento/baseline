"""One live call between a visitor and the AI, analyzed by Baseline in real time.

Audio paths
    visitor mic PCM ──► turn VAD (own segmenter) ──► barge-in + speaking events
                    │                          └──► (role agent) STT ──► visitor turn
                    └──► (role scammer) CallPipeline (VAD+STT+detectors) ──► transcript ──► visitor turn
    visitor turn ──► Brain (persona LLM, sentence stream) ──► TTS ──► Player (paced 50 ms frames)
                                                                    ├──► client (binary PCM + ai_level)
                                                                    └──► (role agent) CallPipeline.feed_utterance
                                                                         with the LLM text as transcript

Turn-taking: replies are generated one at a time; visitor turns that arrive meanwhile are merged
into the next reply, and a reply doesn't start while the visitor is mid-utterance. If the
visitor speaks for BARGE_IN_MS while the AI is talking, the AI stops (stop_audio) and listens.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from caller.brain import Brain
from caller.personas import CUSTOMER, SCENARIOS, Persona
from caller.report import VERDICT_LABELS, save_report
from caller.tts import TTSProvider
from core import Utterance
from events import Event, TranscriptEvent
from pipeline import CallPipeline, pcm16_to_float
from segmenter import Segmenter

log = logging.getLogger(__name__)

SendJson = Callable[[dict], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]
UNANALYZED_ID_BASE = 1000  # utterance ids for lines that skip the pipeline (never collide with analyzed ids)


@dataclass
class VisitorTurn:
    text: str
    t_start: float
    t_end: float
    ready_at: float  # monotonic: when the turn's text was known
    source: str  # "audio" | "text"
    vad_end_at: float | None = None  # monotonic: when the VAD closed the utterance (audio only)
    stt_ms: float | None = None


@dataclass
class TurnTiming:
    turn: int
    source: str
    start_at: float  # reference point (VAD end for audio, text arrival for text)
    vad_end_at: float | None = None
    stt_ms: float | None = None
    llm_first_at: float | None = None
    tts_first_at: float | None = None
    first_audio_at: float | None = None

    def as_dict(self, hangover_ms: float) -> dict:
        def ms(a, b):
            return round((a - b) * 1000, 1) if a is not None and b is not None else None

        d = {"turn": self.turn, "source": self.source,
             "visitor_end_to_first_audio_ms": ms(self.first_audio_at, self.start_at),
             "llm_first_sentence_ms": ms(self.llm_first_at, self.start_at),
             "tts_first_audio_ms": ms(self.tts_first_at, self.llm_first_at)}
        if self.source == "audio":
            d["stt_ms"] = self.stt_ms
            v = d["visitor_end_to_first_audio_ms"]
            d["speech_end_to_first_audio_ms"] = round(v + hangover_ms, 1) if v is not None else None
        return d


@dataclass
class Collected:
    transcript: list[dict] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)
    trust: list[dict] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    turns: list[TurnTiming] = field(default_factory=list)


class Player:
    """Paces AI audio to the client in fixed frames at real time (+ a small lead), emits
    ai_level ~20 Hz aligned with playback, and records what was actually played."""

    def __init__(self, call: LiveCall):
        self.c = call
        st = call.settings
        self.sr = st.sample_rate
        self.chunk_bytes = int(self.sr * st.audio_chunk_ms / 1000) * 2
        self.chunk_s = st.audio_chunk_ms / 1000
        self.lead_s = st.audio_lead_ms / 1000
        self.pending = bytearray()
        self.next_play_at: float | None = None  # monotonic time the next frame starts playing
        self.first_play_at: float | None = None
        self.levels: deque[tuple[float, float]] = deque()
        self.played: list[np.ndarray] = []  # float frames sent
        self.frame_sentence: list[int] = []  # sentence index per frame
        self.sentence_idx = 0
        self._level_task: asyncio.Task | None = None

    async def _level_loop(self) -> None:
        while True:
            await asyncio.sleep(self.chunk_s)
            now = time.monotonic()
            last = None
            while self.levels and self.levels[0][0] <= now:
                last = self.levels.popleft()[1]
            if last is not None:
                await self.c.send_json({"type": "ai_level", "rms": last})

    async def write(self, pcm: bytes) -> None:
        self.pending += pcm
        while len(self.pending) >= self.chunk_bytes:
            frame = bytes(self.pending[:self.chunk_bytes])
            del self.pending[:self.chunk_bytes]
            await self._send(frame)

    async def flush(self) -> None:
        if self.pending:
            frame = bytes(self.pending[: len(self.pending) - len(self.pending) % 2])
            self.pending.clear()
            if frame:
                await self._send(frame)

    async def _send(self, frame: bytes) -> None:
        now = time.monotonic()
        if self.first_play_at is None:
            self.first_play_at = now
            self.next_play_at = now
            self._level_task = asyncio.create_task(self._level_loop())
            await self.c.on_first_audio()
        self.next_play_at = max(self.next_play_at, now)  # underrun: the client resumes immediately
        wait = (self.next_play_at - now) - self.lead_s
        if wait > 0:
            await asyncio.sleep(wait)
        x = pcm16_to_float(frame)
        rms = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
        await self.c.send_bytes(frame)
        self.levels.append((self.next_play_at, round(min(1.0, rms * 4.0), 3)))
        self.played.append(x)
        self.frame_sentence.append(self.sentence_idx)
        self.next_play_at += len(x) / self.sr

    async def drain(self) -> None:
        """Wait until the client has played everything sent."""
        if self.next_play_at is not None:
            delay = self.next_play_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)

    def stop(self) -> None:
        if self._level_task is not None:
            self._level_task.cancel()

    def played_audio(self, cut: bool) -> tuple[np.ndarray, int]:
        """(audio actually heard, number of sentences started). On barge-in, frames the client
        had buffered but not played yet are dropped."""
        frames, sents = self.played, self.frame_sentence
        if cut and self.first_play_at is not None:
            heard_s = time.monotonic() - self.first_play_at
            n, t = 0, 0.0
            while n < len(frames) and t < heard_s:
                t += len(frames[n]) / self.sr
                n += 1
            frames, sents = frames[:n], sents[:n]
        audio = np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)
        return audio, (max(sents) + 1 if sents else 0)


class LiveCall:
    def __init__(self, *, session, settings, send_json: SendJson, send_bytes: SendBytes, persona: Persona,
                 brain: Brain, tts: TTSProvider, stt, pipeline: CallPipeline | None = None,
                 segmenter: Segmenter, customer_enrolled: bool, llm_info: dict, on_end=None):
        self.session = session
        self.settings = settings
        self._send_json = send_json
        self._send_bytes = send_bytes
        self.persona = persona
        self.brain = brain
        self.tts = tts
        self.stt = stt
        self.turn_vad = segmenter
        self.customer_enrolled = customer_enrolled
        self.llm_info = llm_info
        self.on_end = on_end
        self.role = session.role
        # role agent: Baseline analyzes the AI caller; role scammer: the visitor's mic
        self.analyzed_speaker = "ai" if self.role == "agent" else "visitor"
        self.pipe = pipeline if pipeline is not None else CallPipeline(self._on_pipe_event, settings)
        self.pipe.emit = self._on_pipe_event
        self.col = Collected()
        self.t0 = time.monotonic()
        self.turn_q: asyncio.Queue[VisitorTurn] = asyncio.Queue()
        self.stt_q: asyncio.Queue = asyncio.Queue()
        self.ended = asyncio.Event()
        self.end_reason: str | None = None
        self.report_id: str | None = None
        self.ai_speaking = False
        self.visitor_speaking = False
        self.ai_task: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []
        self._next_unanalyzed = UNANALYZED_ID_BASE
        self._mic_samples = 0
        self._cur_timing: TurnTiming | None = None
        self._last_vad_end_at: float | None = None
        self._ending = False
        self._send_ok = True
        frame_ms = 1000 * getattr(segmenter, "frame", 480) / settings.sample_rate
        self._frame_ms = frame_ms

    # ------------------------------------------------------------------ io helpers

    def now(self) -> float:
        return round(time.monotonic() - self.t0, 2)

    async def send_json(self, msg: dict) -> None:
        if not self._send_ok:
            return
        try:
            await self._send_json(msg)
        except Exception:
            self._send_ok = False
            log.debug("send failed (client gone?)", exc_info=True)

    async def send_bytes(self, data: bytes) -> None:
        if not self._send_ok:
            return
        try:
            await self._send_bytes(data)
        except Exception:
            self._send_ok = False

    def _transcript(self, *, utterance_id: int, speaker: str, analyzed: bool, text: str, t_start: float,
                    t_end: float, latency_ms: float | None = None) -> dict:
        d = TranscriptEvent(utterance_id=utterance_id, t_start=t_start, t_end=t_end, text=text,
                            latency_ms=latency_ms, speaker=speaker, analyzed=analyzed).model_dump()
        self.col.transcript.append({k: d[k] for k in ("utterance_id", "speaker", "analyzed", "text", "t_start",
                                                       "t_end", "latency_ms")})
        return d

    async def _emit_unanalyzed(self, speaker: str, text: str, t_start: float, t_end: float,
                               latency_ms: float | None = None) -> None:
        uid = self._next_unanalyzed
        self._next_unanalyzed += 1
        await self.send_json(self._transcript(utterance_id=uid, speaker=speaker, analyzed=False, text=text,
                                              t_start=t_start, t_end=t_end, latency_ms=latency_ms))

    async def _on_pipe_event(self, ev: Event) -> None:
        d = ev.model_dump()
        t = self.now()
        if ev.type == "transcript":
            d = self._transcript(utterance_id=ev.utterance_id, speaker=self.analyzed_speaker, analyzed=True,
                                 text=ev.text, t_start=ev.t_start, t_end=ev.t_end, latency_ms=ev.latency_ms)
            if self.role == "scammer" and not self._ending and ev.text.strip():
                src = "text" if ev.t_start == ev.t_end else "audio"
                vad_end = self._last_vad_end_at if src == "audio" else None
                self.turn_q.put_nowait(VisitorTurn(ev.text, ev.t_start, ev.t_end, time.monotonic(), src,
                                                   vad_end_at=vad_end, stt_ms=ev.latency_ms))
        elif ev.type == "signal":
            self.col.signals.append(d | {"t": t})
        elif ev.type == "trust":
            self.col.trust.append(d | {"t": t})
        elif ev.type == "alert":
            self.col.alerts.append(d | {"t": t})
        elif ev.type == "status":
            if d.get("state") == "error":
                self.col.errors.append(d.get("message", ""))
            return  # not part of the live contract
        await self.send_json(d)

    # ------------------------------------------------------------------ lifecycle

    def call_started_event(self) -> dict:
        return {"type": "call_started", "session_id": self.session.id, "role": self.role,
                "scenario": self.session.scenario, "voice": self.session.voice,
                "customer": {"id": CUSTOMER.id, "name": CUSTOMER.name, "account_mask": CUSTOMER.account_mask,
                             "enrolled": self.customer_enrolled},
                "audio": {"sample_rate": self.settings.sample_rate, "format": "pcm_s16le"},
                "max_call_s": int(self.settings.max_call_seconds)}

    async def start(self) -> None:
        self.t0 = time.monotonic()
        self.pipe.start_call(customer_id=CUSTOMER.id)
        self.turn_vad.reset()
        warm = getattr(self.tts, "warm", None)
        if warm is not None:
            with suppress(Exception):
                await warm(self.session.voice)
        await self.send_json(self.call_started_event())
        self._tasks = [asyncio.create_task(self._turn_worker(), name="turns"),
                       asyncio.create_task(self._timer(), name="timer")]
        if self.role == "agent":
            self._tasks.append(asyncio.create_task(self._stt_worker(), name="stt"))

    async def _timer(self) -> None:
        cap = float(self.settings.max_call_seconds)
        warn = min(float(self.settings.call_warning_seconds), cap)
        await asyncio.sleep(cap - warn)
        await self.send_json({"type": "warning", "message": f"Call ends in {int(warn)} seconds.",
                              "seconds_left": int(warn)})
        await asyncio.sleep(warn)
        asyncio.create_task(self.end("timeout"))

    async def wait(self) -> None:
        await self.ended.wait()

    # ------------------------------------------------------------------ visitor input

    def feed_mic(self, data: bytes) -> None:
        if self._ending:
            return
        x = pcm16_to_float(data)
        self._mic_samples += len(x)
        segs = self.turn_vad.feed(x)
        if self.role == "scammer":
            self.pipe.feed_float(x)
        speech_ms = getattr(self.turn_vad, "_speech_frames", 0) * self._frame_ms
        in_speech = bool(getattr(self.turn_vad, "_in_speech", False))
        if in_speech and not self.visitor_speaking and speech_ms >= self.settings.vad_min_speech_ms:
            self.visitor_speaking = True
            asyncio.create_task(self.send_json({"type": "speaking", "who": "visitor", "state": "start"}))
        if self.ai_speaking and in_speech and speech_ms >= self.settings.barge_in_ms:
            self.barge_in()
        for seg in segs:
            self._last_vad_end_at = time.monotonic()
            if self.role == "agent":
                self.stt_q.put_nowait((seg, self._last_vad_end_at))
        if segs or (self.visitor_speaking and not in_speech):
            if self.visitor_speaking:
                self.visitor_speaking = False
                asyncio.create_task(self.send_json({"type": "speaking", "who": "visitor", "state": "end"}))

    async def feed_text(self, text: str) -> None:
        text = " ".join(str(text).split())[:500]
        if not text or self._ending:
            return
        t = self.now()
        if self.role == "scammer":
            self.pipe.feed_text(text, t, t)  # transcript comes back through _on_pipe_event -> turn queue
        else:
            await self._emit_unanalyzed("visitor", text, t, t)
            self.turn_q.put_nowait(VisitorTurn(text, t, t, time.monotonic(), "text"))

    async def _stt_worker(self) -> None:
        sr = self.settings.sample_rate
        n = 0
        while True:
            seg, vad_end = await self.stt_q.get()
            t_start = round(seg.t_start, 2)
            t_end = round(seg.t_end, 2)
            t = time.perf_counter()
            try:
                text = (await self.stt.transcribe(Utterance(id=n, audio=seg.audio, sample_rate=sr,
                                                            t_start=t_start, t_end=t_end))).strip()
            except Exception as e:
                log.exception("visitor STT failed")
                self.col.errors.append(f"visitor STT failed: {e}")
                text = ""
            n += 1
            stt_ms = round((time.perf_counter() - t) * 1000, 1)
            if not text or self._ending:
                continue
            await self._emit_unanalyzed("visitor", text, t_start, t_end, stt_ms)
            self.turn_q.put_nowait(VisitorTurn(text, t_start, t_end, time.monotonic(), "audio",
                                               vad_end_at=vad_end, stt_ms=stt_ms))

    # ------------------------------------------------------------------ AI turns

    def barge_in(self) -> None:
        if self.ai_task is not None and not self.ai_task.done():
            log.info("barge-in: visitor interrupted the AI")
            self.ai_task.cancel()

    async def _turn_worker(self) -> None:
        opener = self.persona.opener()
        await self._run_ai_turn(None, fixed=opener)
        while True:
            turn = await self.turn_q.get()
            # don't talk over the visitor: wait (bounded) until they finish, then merge
            for _ in range(80):
                if not self.visitor_speaking:
                    break
                await asyncio.sleep(0.05)
            turns = [turn]
            while not self.turn_q.empty():
                turns.append(self.turn_q.get_nowait())
            for t in turns:
                self.brain.add_visitor(t.text)
            await self._run_ai_turn(turns[-1])

    async def _run_ai_turn(self, turn: VisitorTurn | None, fixed: str | None = None) -> None:
        self.ai_task = asyncio.create_task(self._ai_turn(turn, fixed))
        await asyncio.wait({self.ai_task})  # never raises on the inner task's cancel (barge-in)

    async def on_first_audio(self) -> None:
        self.ai_speaking = True
        if self._cur_timing is not None:
            self._cur_timing.first_audio_at = time.monotonic()
        await self.send_json({"type": "speaking", "who": "ai", "state": "start"})

    async def _ai_turn(self, turn: VisitorTurn | None, fixed: str | None) -> None:
        timing = None
        if turn is not None:
            ref = turn.vad_end_at if (turn.source == "audio" and turn.vad_end_at) else turn.ready_at
            timing = TurnTiming(turn=len(self.col.turns) + 1, source=turn.source, start_at=ref,
                                vad_end_at=turn.vad_end_at, stt_ms=turn.stt_ms)
            self.col.turns.append(timing)
        self._cur_timing = timing
        player = Player(self)
        sentences: list[str] = []
        sent_q: asyncio.Queue = asyncio.Queue()
        t_ai_start = self.now()
        cut = False

        async def produce() -> None:
            try:
                if fixed is not None:
                    await sent_q.put(fixed)
                else:
                    async for s in self.brain.reply():
                        if timing is not None and timing.llm_first_at is None:
                            timing.llm_first_at = time.monotonic()
                        await sent_q.put(s)
            finally:
                await sent_q.put(None)

        producer = asyncio.create_task(produce())
        try:
            while True:
                s = await sent_q.get()
                if s is None:
                    break
                sentences.append(s)
                player.sentence_idx = len(sentences) - 1
                async for pcm in self.tts.stream(s, self.session.voice):
                    if timing is not None and timing.tts_first_at is None:
                        timing.tts_first_at = time.monotonic()
                    await player.write(pcm)
                await player.flush()
            await player.drain()
        except asyncio.CancelledError:
            cut = True
            await self.send_json({"type": "stop_audio"})
        except Exception as e:
            log.exception("AI turn failed")
            self.col.errors.append(f"AI turn failed: {e}")
        finally:
            producer.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await producer
            player.stop()
            was_speaking = self.ai_speaking
            self.ai_speaking = False
            self._cur_timing = None
            audio, n_started = player.played_audio(cut)
            spoken = " ".join(sentences[:n_started] if cut else sentences).strip()
            if cut and spoken:
                spoken += " —"
            if was_speaking:
                await self.send_json({"type": "speaking", "who": "ai", "state": "end"})
            if spoken.strip(" —"):
                self.brain.add_ai(spoken)
                t_end = round(t_ai_start + len(audio) / self.settings.sample_rate, 2)
                if self.role == "agent":
                    # Baseline analyzes the caller channel: the AI's own audio, with its script as text
                    self.pipe.feed_utterance(audio, t_ai_start, t_end, text=spoken)
                else:
                    await self._emit_unanalyzed("ai", spoken, t_ai_start, t_end)

    # ------------------------------------------------------------------ end

    async def end(self, reason: str = "hangup") -> str | None:
        """Idempotent. Stops audio, flushes analysis, persists the report, sends call_ended."""
        if self._ending:
            await self.ended.wait()
            return self.report_id
        self._ending = True
        self.end_reason = reason
        if self.ai_task is not None and not self.ai_task.done():
            self.ai_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.ai_task
        current = asyncio.current_task()
        for t in self._tasks:
            if t is not current:
                t.cancel()
        for t in self._tasks:
            if t is not current:
                with suppress(asyncio.CancelledError, Exception):
                    await t
        try:
            await asyncio.wait_for(self.pipe.end_call(), timeout=8.0)
        except Exception as e:
            log.warning("pipeline flush did not finish: %s", e)
            self.col.errors.append(f"analysis flush incomplete: {type(e).__name__}")
        report = self.build_report(reason)
        self.report_id = report["id"]
        try:
            save_report(self.settings.reports_dir, report)
        except Exception:
            log.exception("could not save report")
        await self.send_json({"type": "call_ended", "reason": reason, "report_id": self.report_id,
                              "reveal": {"role": self.role, "scenario": self.session.scenario,
                                         "persona_label": self.persona.label, "voice": self.session.voice,
                                         "tts": self.tts.name}})
        with suppress(Exception):
            await self.pipe.close()
        if self.on_end is not None:
            with suppress(Exception):
                await self.on_end(self)
        self.ended.set()
        return self.report_id

    def build_report(self, reason: str) -> dict:
        f = self.pipe.fusion
        alert = f.alert_event()
        turns = [t.as_dict(self.settings.vad_hangover_ms) for t in self.col.turns]
        lat = [t["visitor_end_to_first_audio_ms"] for t in turns if t["visitor_end_to_first_audio_ms"] is not None]
        fraud_ev = f.evidence.get("fraud")
        evidence = f.top_patterns() if fraud_ev else []
        if not evidence and "fraud" in f.signals:
            evidence = list(f.signals["fraud"].details.get("patterns", []) or [])
        sc = SCENARIOS.get(self.session.scenario)
        call_s = round(time.monotonic() - self.t0, 2)
        return {
            "id": self.session.id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ended_reason": reason,
            "meta": {
                "role": self.role, "scenario": self.session.scenario,
                "scenario_label": sc.label if sc else None,
                "voice": self.session.voice, "tts": self.tts.name, "llm": self.llm_info,
                "persona": {"label": self.persona.label, "summary": self.persona.summary},
                "customer": {"id": CUSTOMER.id, "name": CUSTOMER.name, "account_mask": CUSTOMER.account_mask,
                             "enrolled": self.customer_enrolled},
                "analyzed_channel": self.analyzed_speaker,
                "requested": self.session.requested,
                "providers": self.pipe.providers,
            },
            "durations": {"queue_wait_s": self.session.queue_wait_s, "call_s": call_s},
            "transcript": sorted(self.col.transcript, key=lambda x: (x["t_start"], x["utterance_id"])),
            "signals": self.col.signals,
            "trust": self.col.trust,
            "alerts": self.col.alerts,
            "verdict": {
                "level": f.level if f.level != "none" else alert.level,
                "label": VERDICT_LABELS.get(alert.level, alert.level),
                "trust": round(f.trust, 1),
                "fired": f.fired(),
                "signals_fired_ever": f.evidence_signals(),
                "reasons": alert.reasons,
                "suggested_action": alert.suggested_action,
                # the visitor/AI fraudster is always a fraudster in this simulation
                "caught": alert.level != "none",
                "final_signals": {k: {"score": round(s.score, 3), "confidence": round(s.confidence, 3),
                                      "reason": s.reason} for k, s in f.signals.items() if s.seen},
            },
            "fraud_evidence": evidence,
            "latencies": {
                "turns": turns,
                "mean_turn_ms": round(statistics.mean(lat), 1) if lat else None,
                "p50_turn_ms": round(statistics.median(lat), 1) if lat else None,
                "max_turn_ms": round(max(lat), 1) if lat else None,
                "pipeline": self.pipe.utterance_timings,
            },
            "errors": self.col.errors,
        }
