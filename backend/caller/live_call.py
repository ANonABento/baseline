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
import bisect
import logging
import statistics
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone

import re

import numpy as np

from caller import intervention
from caller.brain import Brain
from caller.personas import CUSTOMER, PRESSURE_HINTS, SCENARIOS, Persona, agenda_for, normalize_role, pressure_for_time, pressure_for_turn
from caller.recording import CallRecorder
from caller.report import VERDICT_LABELS, save_report
from caller.tts import TTSProvider, baseline_voice
from credential import issue_for_report
from core import Utterance
from detectors import client_risk, session_signals
from detectors.session_signals import analyse, decision_tags
from events import Event, SignalEvent, TranscriptEvent
from pipeline import CallPipeline, pcm16_to_float
from segmenter import Segmenter

log = logging.getLogger(__name__)

SendJson = Callable[[dict], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]
UNANALYZED_ID_BASE = 1000  # utterance ids for lines that skip the pipeline (never collide with analyzed ids)


_TRAILING = {"and", "but", "so", "because", "or", "um", "uh", "umm", "uhh", "like", "the", "a", "an", "my",
             "i", "to", "if", "that", "then", "with", "of", "for", "is", "was", "just", "well"}
_COMPLETE_SHORT = {"yes", "yeah", "yep", "no", "nope", "okay", "ok", "hello", "hi", "hey", "sure", "what", "why",
                   "who", "who is this", "who's this", "bye", "goodbye", "thanks", "thank you", "right", "correct",
                   "sorry", "pardon", "huh", "really", "no thanks", "not interested", "hold on", "one sec"}


def looks_unfinished(text: str) -> bool:
    """Heuristic: the visitor paused mid-thought (trailing conjunction/filler, comma, or a fragment)."""
    t = text.strip().lower()
    if not t:
        return False
    if re.search(r"(,|-|\u2014|\.\.\.|\u2026)$", t):
        return True
    words = re.findall(r"[a-z']+", t)
    if not words:
        return False
    if " ".join(words) in _COMPLETE_SHORT:
        return False
    if words[-1] in _TRAILING:
        return True
    return len(words) <= 2 and not re.search(r"[.!?]$", t)


@dataclass
class VisitorTurn:
    text: str
    t_start: float
    t_end: float
    ready_at: float  # monotonic: when the turn's text was known
    source: str  # "audio" | "text" | "resume" (carry on after Baseline spoke; not a visitor turn)
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
        self.role = normalize_role(session.role)
        self.scenario = SCENARIOS.get(session.scenario)
        # role client: Baseline analyzes the AI caller (+ the visitor's words with client_risk);
        # role scammer: the visitor's mic. The Digital Twin is built from the analysed speaker:
        self.analyzed_speaker = "ai" if self.role == "client" else "visitor"
        self.pressure: list[dict] = []  # scripted pressure the AI applied (role client): [{t, level}]
        self._ai_turns = 0
        self.pipe = pipeline if pipeline is not None else CallPipeline(self._on_pipe_event, settings)
        self.pipe.emit = self._on_pipe_event
        if self.role in ("client", "scammer") and not (self.scenario and self.scenario.claims_customer):
            # the caller doesn't claim to be someone the callee knows: voice verification has nothing to compare
            self.pipe.detectors = [d for d in self.pipe.detectors if d.name != "speaker"]
        # interventions (role client)
        self.policy = intervention.InterventionPolicy(min_gap_s=float(getattr(settings, "intervention_min_gap_s", 10.0)))
        self.interventions: list[dict] = []
        self.actions: list[dict] = []
        self.suspect_t: float | None = None
        self.first_flag_t: float | None = None
        self.first_high_t: float | None = None
        self._ai_gate = asyncio.Event()  # cleared while Baseline speaks: the AI caller must not talk
        self._ai_gate.set()
        self._gate_opened_at = 0.0
        self._baseline_task: asyncio.Task | None = None
        self._deferred_task: asyncio.Task | None = None
        self.baseline_audio_s = 0.0
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
        self._mic_ends: list[int] = []  # cumulative mic sample count after each chunk ...
        self._mic_walls: list[float] = []  # ... and the call time it arrived (push-to-talk sends audio in bursts)
        self._cur_timing: TurnTiming | None = None
        self._last_vad_end_at: float | None = None
        self._last_speech_at = 0.0  # monotonic: last mic frame the turn VAD counted as speech
        self.ptt_mode = False  # the client sent ptt messages: press/release marks turns, no silence hold
        self.ptt_active = False
        self._stt_pending = 0  # visitor segments queued for or in our STT worker
        self._ending = False
        self._send_ok = True
        frame_ms = 1000 * getattr(segmenter, "frame", 480) / settings.sample_rate
        self._frame_ms = frame_ms
        self.record_audio = bool((getattr(session, "requested", None) or {}).get("record_audio", False))
        self.recorder = CallRecorder(settings.sample_rate, record_visitor=self.record_audio)

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
                               latency_ms: float | None = None) -> int:
        uid = self._next_unanalyzed
        self._next_unanalyzed += 1
        await self.send_json(self._transcript(utterance_id=uid, speaker=speaker, analyzed=False, text=text,
                                              t_start=t_start, t_end=t_end, latency_ms=latency_ms))
        return uid

    async def _emit_decisions(self, uid: int, text: str, t: float) -> None:
        """Keyword-detected decision phrases in a visitor turn (shown as phrases, never verdicts)."""
        for tag in decision_tags(text):
            await self.send_json({"type": "decision", "event": tag, "utterance_id": uid, "t": round(t, 1)})

    async def _visitor_line(self, text: str, t_start: float, t_end: float, latency_ms: float | None = None) -> int:
        """A visitor line that skips the audio pipeline (role client). Baseline still checks the
        client's own words (client_risk) and fuses that soft signal with the caller's."""
        uid = await self._emit_unanalyzed("visitor", text, t_start, t_end, latency_ms)
        if self.role != "client" or self._ending:
            return uid
        t0 = time.perf_counter()
        caller = [x["text"] for x in self.col.transcript if x["speaker"] == "ai"][-2:]
        r = client_risk.assess(text, caller)
        f = self.pipe.fusion
        f.update(r)
        await self._on_pipe_event(SignalEvent(**r.model_dump(), utterance_id=uid,
                                              latency_ms=round((time.perf_counter() - t0) * 1000, 2)))
        await self._on_pipe_event(f.trust_event(uid))
        alert = f.alert_if_changed()
        if alert is not None:
            self.pipe.last_alert = alert
            await self._on_pipe_event(alert)
        return uid

    def _mic_to_call_time(self, t_audio: float) -> float:
        """Pipeline times count only the mic samples received (push-to-talk sends audio in bursts);
        map them to call time so the visitor's turns line up with the AI's wall-clock lines."""
        if not self._mic_ends:
            return t_audio
        s = t_audio * self.settings.sample_rate
        i = min(bisect.bisect_left(self._mic_ends, s), len(self._mic_ends) - 1)
        return round(self._mic_walls[i] - (self._mic_ends[i] - s) / self.settings.sample_rate, 2)

    async def _emit_behaviour(self) -> None:
        """Session behavioural signals so far (tone drift, speech rate, hesitation, response and
        de-escalation latency, decisions), recomputed after every analysed turn."""
        try:
            b = session_signals.analyse({"transcript": self.col.transcript, "signals": self.col.signals},
                                        self.pressure, person=self.analyzed_speaker)
        except Exception:  # noqa: BLE001  never break the call over a summary
            log.debug("behaviour summary failed", exc_info=True)
            return
        await self.send_json({"type": "behaviour", "t": self.now(), **b})

    async def _on_pipe_event(self, ev: Event) -> None:
        d = ev.model_dump()
        t = self.now()
        if ev.type == "transcript":
            t_start, t_end = ev.t_start, ev.t_end
            if self.role == "scammer" and t_start != t_end:  # audio turn (typed text already uses call time)
                t_start, t_end = self._mic_to_call_time(t_start), self._mic_to_call_time(t_end)
            d = self._transcript(utterance_id=ev.utterance_id, speaker=self.analyzed_speaker, analyzed=True,
                                 text=ev.text, t_start=t_start, t_end=t_end, latency_ms=ev.latency_ms)
            await self._emit_decisions(ev.utterance_id, ev.text, t_start)
            if self.role == "scammer" and not self._ending and ev.text.strip():
                src = "text" if ev.t_start == ev.t_end else "audio"
                vad_end = self._last_vad_end_at if src == "audio" else None
                self.turn_q.put_nowait(VisitorTurn(ev.text, t_start, t_end, time.monotonic(), src,
                                                   vad_end_at=vad_end, stt_ms=ev.latency_ms))
        elif ev.type == "signal":
            self.col.signals.append(d | {"t": t})
        elif ev.type == "trust":
            self.col.trust.append(d | {"t": t})
        elif ev.type == "alert":
            self.col.alerts.append(d | {"t": t})
            if ev.level != "none" and self.first_flag_t is None:
                self.first_flag_t = t
            if ev.level == "high" and self.first_high_t is None:
                self.first_high_t = t
            await self.send_json(d)
            if self.role in ("client", "scammer"):
                await self._consider_intervention(ev.level)
            return
        elif ev.type == "status":
            if d.get("state") == "error":
                self.col.errors.append(d.get("message", ""))
            return  # not part of the live contract
        await self.send_json(d)
        if (ev.type == "transcript" and ev.text.strip()) or (ev.type == "signal" and ev.signal == "prosody"):
            await self._emit_behaviour()

    # ------------------------------------------------------------------ interventions (role client)

    def _reasons(self) -> list[str]:
        f = self.pipe.fusion
        pats = set(f.evidence["fraud"].patterns) if "fraud" in f.evidence else set()
        cl = f.evidence.get("client")
        kind = cl.details.get("kind") if cl else None
        rid = cl.details.get("reason_id") if cl else None
        asked = cl.details.get("asked") if cl else None
        return intervention.candidates(pats, kind, rid, self.session.scenario, f.evidence.keys(), asked)

    async def _consider_intervention(self, level: str) -> None:
        if self._ending:
            return
        d = self.policy.decide(level, self._reasons(), self.now())
        if d.reason_id is not None:
            await self._intervene(level, d.reason_id)
        elif d.defer_s is not None and (self._deferred_task is None or self._deferred_task.done()):
            async def later(delay: float) -> None:
                await asyncio.sleep(delay + 0.05)
                await self._consider_intervention(self.pipe.fusion.level)
            self._deferred_task = asyncio.create_task(later(d.defer_s))

    async def _intervene(self, level: str, reason_id: str) -> None:
        t = self.now()
        self.policy.record(level, reason_id, t)
        speak = level == "high" and (self._baseline_task is None or self._baseline_task.done())
        # introduce Baseline the first time it shows up, and the first time it speaks
        first = not self.interventions or (speak and not any(i["spoken"] for i in self.interventions))
        message = intervention.message_for(reason_id, first=first)
        self.interventions.append({"t": t, "level": level, "reason_id": reason_id, "message": message, "spoken": speak})
        await self.send_json({"type": "intervention", "level": level, "message": message, "reason_id": reason_id,
                              "to": "victim" if self.role == "scammer" else "visitor"})
        if self.role == "scammer":
            # the AI is the scammer's target: Baseline warns ITS phone, the visitor (scammer) only sees that it
            # happened. The victim reacts to the warning from its next turn on.
            self.brain.pressure_hint += f"\nWARNINGS: your bank app just warned you on screen: \"{message}\""
            return
        if level == "high" and not self.actions:
            for a in intervention.ACTIONS:
                self.actions.append({"t": self.now(), "kind": a["kind"], "message": a["message"]})
                await self.send_json(dict(a))
        if speak:
            self._baseline_task = asyncio.create_task(self._speak_baseline(message, reason_id), name="baseline-voice")

    async def _speak_baseline(self, text: str, reason_id: str) -> None:
        """Baseline's voice, to the visitor only: pause the AI caller, then stream TTS frames between
        baseline_audio_start / baseline_audio_end. Never added to the fraudster's history or the pipeline."""
        self._ai_gate.clear()
        started = False
        resume = False
        try:
            if self.ai_task is not None and not self.ai_task.done():
                resume = True  # the caller was mid-reply: let it carry on after Baseline has spoken
                self.ai_task.cancel()  # sends stop_audio; the cut line is recorded as interrupted
                await asyncio.wait({self.ai_task})
            st = self.settings
            sr = st.sample_rate
            chunk = int(sr * st.audio_chunk_ms / 1000) * 2
            lead = st.audio_lead_ms / 1000
            await self.send_json({"type": "baseline_audio_start", "reason_id": reason_id, "text": text,
                                  "sample_rate": sr})
            started = True
            buf = bytearray()
            next_at: float | None = None
            total = 0

            async def send(frame: bytes) -> None:
                nonlocal next_at, total
                now = time.monotonic()
                next_at = now if next_at is None else max(next_at, now)
                wait = (next_at - now) - lead
                if wait > 0:
                    await asyncio.sleep(wait)
                await self.send_bytes(frame)
                next_at += len(frame) / 2 / sr
                total += len(frame) // 2

            async for pcm in self.tts.stream(text, baseline_voice(self.tts, self.settings)):
                buf += pcm
                while len(buf) >= chunk:
                    frame = bytes(buf[:chunk])
                    del buf[:chunk]
                    await send(frame)
            if len(buf) >= 2:
                await send(bytes(buf[: len(buf) - len(buf) % 2]))
            if next_at is not None:
                delay = next_at - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
            self.baseline_audio_s += total / sr
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("Baseline voice failed")
            self.col.errors.append(f"Baseline voice failed: {e}")
        finally:
            if started:
                await self.send_json({"type": "baseline_audio_end", "reason_id": reason_id})
            self._ai_gate.set()
            self._gate_opened_at = time.monotonic()
            if resume and not self._ending:
                self.turn_q.put_nowait(VisitorTurn("", self.now(), self.now(), time.monotonic(), "resume"))

    async def suspect(self) -> None:
        """The visitor pressed "This feels like a scam" (recorded once)."""
        if self.suspect_t is None and not self._ending:
            self.suspect_t = self.now()
        await self.send_json({"type": "suspect_ack", "t": self.suspect_t})

    # ------------------------------------------------------------------ lifecycle

    def call_started_event(self) -> dict:
        return {"type": "call_started", "session_id": self.session.id, "role": self.role,
                "scenario": self.session.scenario, "voice": self.session.voice,
                "customer": {"id": CUSTOMER.id, "name": CUSTOMER.name, "account_mask": CUSTOMER.account_mask,
                             "enrolled": self.customer_enrolled},
                "audio": {"sample_rate": self.settings.sample_rate, "format": "pcm_s16le"},
                "max_call_s": int(self.settings.max_call_seconds),
                "scenario_label": self.scenario.label if self.scenario else None,
                "agenda": agenda_for(self.session.scenario) if self.role == "scammer" else None,
                "visitor_as": self._visitor_as()}

    def _visitor_as(self) -> str:
        if self.role == "scammer":
            return "The scammer"
        if self.session.scenario == "grandchild":
            return f"{CUSTOMER.name}'s grandparent"
        return CUSTOMER.name

    def you_vs_baseline(self) -> dict:
        return {"visitor_flag_t": self.suspect_t, "baseline_flag_t": self.first_flag_t,
                "baseline_high_t": self.first_high_t,
                "interventions": len(self.interventions), "actions": [a["kind"] for a in self.actions]}

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
        if self.role == "client":
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
        self.recorder.add_mic(time.monotonic() - self.t0, x)
        self._mic_ends.append(self._mic_samples)
        self._mic_walls.append(time.monotonic() - self.t0)
        segs = self.turn_vad.feed(x)
        if self.role == "scammer":
            self.pipe.feed_float(x)
        speech_ms = getattr(self.turn_vad, "_speech_frames", 0) * self._frame_ms
        in_speech = bool(getattr(self.turn_vad, "_in_speech", False))
        if in_speech and getattr(self.turn_vad, "_silence_run", 0) == 0:
            self._last_speech_at = time.monotonic()
        if in_speech and not self.visitor_speaking and speech_ms >= self.settings.vad_min_speech_ms:
            self.visitor_speaking = True
            asyncio.create_task(self.send_json({"type": "speaking", "who": "visitor", "state": "start"}))
        if self.ai_speaking and in_speech and speech_ms >= self.settings.barge_in_ms:
            self.barge_in()
        for seg in segs:
            self._last_vad_end_at = time.monotonic()
            self._to_stt(seg)
        if segs or (self.visitor_speaking and not in_speech):
            if self.visitor_speaking:
                self.visitor_speaking = False
                asyncio.create_task(self.send_json({"type": "speaking", "who": "visitor", "state": "end"}))

    def _to_stt(self, seg) -> None:
        if self.role == "client":
            self._stt_pending += 1
            self.stt_q.put_nowait((seg, self._last_vad_end_at))

    def ptt(self, state: str) -> None:
        """Push-to-talk. down: the visitor holds the talk key (interrupts the AI). up: sent after the
        release tail; the held speech is closed into a turn now instead of waiting for silence."""
        if self._ending:
            return
        self.ptt_mode = True
        if state == "down":
            self.ptt_active = True
            self.barge_in()
            return
        if state != "up" or not self.ptt_active:
            return
        self.ptt_active = False
        for seg in self.turn_vad.flush():
            self._last_vad_end_at = time.monotonic()
            self._to_stt(seg)
        if self.role == "scammer":
            for seg in self.pipe.segmenter.flush():
                self.pipe._enqueue(seg)
        if self.visitor_speaking:
            self.visitor_speaking = False
            asyncio.create_task(self.send_json({"type": "speaking", "who": "visitor", "state": "end"}))

    def _transcribing(self) -> bool:
        """Held speech still on its way to a visitor turn (our STT worker or the pipeline's queue)."""
        if self._stt_pending > 0:
            return True
        return self.role != "client" and getattr(self.pipe._queue, "_unfinished_tasks", 0) > 0

    async def feed_text(self, text: str) -> None:
        text = " ".join(str(text).split())[:500]
        if not text or self._ending:
            return
        t = self.now()
        if self.role == "scammer":
            self.pipe.feed_text(text, t, t)  # transcript comes back through _on_pipe_event -> turn queue
        else:
            await self._visitor_line(text, t, t)
            self.turn_q.put_nowait(VisitorTurn(text, t, t, time.monotonic(), "text"))

    async def _stt_worker(self) -> None:
        n = 0
        while True:
            seg, vad_end = await self.stt_q.get()
            t_start = round(seg.t_start, 2)
            t_end = round(seg.t_end, 2)
            t = time.perf_counter()
            try:
                await self._stt_one(seg, vad_end, n, t_start, t_end, t)
            finally:
                self._stt_pending = max(0, self._stt_pending - 1)
            n += 1

    async def _stt_one(self, seg, vad_end, n: int, t_start: float, t_end: float, t: float) -> None:
        sr = self.settings.sample_rate
        try:
            text = (await self.stt.transcribe(Utterance(id=n, audio=seg.audio, sample_rate=sr,
                                                        t_start=t_start, t_end=t_end))).strip()
        except Exception as e:
            log.exception("visitor STT failed")
            self.col.errors.append(f"visitor STT failed: {e}")
            text = ""
        stt_ms = round((time.perf_counter() - t) * 1000, 1)
        if not text or self._ending:
            return
        ts, te = self._mic_to_call_time(t_start), self._mic_to_call_time(t_end)
        uid = await self._visitor_line(text, ts, te, stt_ms)
        self.turn_q.put_nowait(VisitorTurn(text, ts, te, time.monotonic(), "audio",
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
            await self._hold_for_end_of_turn(turns)
            for t in turns:
                self.brain.add_visitor(t.text)
            await self._ai_gate.wait()  # Baseline is speaking to the client
            real = [t for t in turns if t.source != "resume"]
            await self._run_ai_turn_merging(real[-1] if real else None)

    async def _hold_for_end_of_turn(self, turns: list[VisitorTurn]) -> None:
        """Don't answer a pause: wait until the visitor has been silent TURN_END_SILENCE_MS (longer if
        the words so far sound unfinished), merging any turn that arrives meanwhile. Typed turns skip it."""
        if self.ptt_mode:
            # push-to-talk: release ends the turn. Wait only while the key is held or held speech is
            # still being transcribed (bounded), merging whatever arrives.
            deadline = time.monotonic() + 30
            while (self.ptt_active or self._transcribing()) and not self._ending and time.monotonic() < deadline:
                try:
                    turns.append(await asyncio.wait_for(self.turn_q.get(), timeout=0.05))
                except asyncio.TimeoutError:
                    pass
            while not self.turn_q.empty():
                turns.append(self.turn_q.get_nowait())
            return
        while turns[-1].source == "audio" and not self._ending:
            text = " ".join(t.text for t in turns if t.source != "resume")
            need = self.settings.turn_end_silence_ms
            if looks_unfinished(text):
                need += self.settings.turn_unfinished_extra_ms
            if self.visitor_speaking:
                quiet_ms = 0.0
            else:
                quiet_ms = (time.monotonic() - self._last_speech_at) * 1000
            if quiet_ms >= need:
                return
            if self.visitor_speaking:
                wait_s = 0.05
            else:
                wait_s = (need - quiet_ms) / 1000
            try:
                turns.append(await asyncio.wait_for(self.turn_q.get(), timeout=wait_s))
            except asyncio.TimeoutError:
                if not self.visitor_speaking and (time.monotonic() - self._last_speech_at) * 1000 >= need:
                    return

    async def _run_ai_turn_merging(self, turn: VisitorTurn | None) -> None:
        """Run a reply, but if the visitor says more before any of it is heard (one sentence split
        in two by the VAD), drop it and requeue so a single reply answers both fragments."""
        self.ai_task = asyncio.create_task(self._ai_turn(turn, None))
        getter = asyncio.create_task(self.turn_q.get())
        await asyncio.wait({self.ai_task, getter}, return_when=asyncio.FIRST_COMPLETED)
        if not getter.done():
            getter.cancel()
            with suppress(asyncio.CancelledError):
                await getter
        if getter.done() and not getter.cancelled():
            if not self.ai_task.done() and not self.ai_speaking:
                log.info("visitor kept talking before the reply was heard; merging turns")
                self.ai_task.cancel()
                await asyncio.wait({self.ai_task})
                if self.col.turns and self.col.turns[-1].first_audio_at is None:
                    self.col.turns.pop()  # the dropped reply never played: not a latency sample
            self.turn_q.put_nowait(getter.result())  # the outer loop picks it up, merged with any others
        await asyncio.wait({self.ai_task})

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
            ref = max(ref, self._gate_opened_at)  # time Baseline spent speaking is not reply latency
            timing = TurnTiming(turn=len(self.col.turns) + 1, source=turn.source, start_at=ref,
                                vad_end_at=turn.vad_end_at, stt_ms=turn.stt_ms)
            self.col.turns.append(timing)
        self._cur_timing = timing
        recent = [x["text"] for x in self.col.transcript if x["speaker"] == "ai"][-5:]
        hint = ("YOUR RECENT LINES (never reuse their wording, numbers, reasons or questions; make a new move that "
                "answers the other person's last words): " + " | ".join(recent)) if recent else ""
        if self.role == "client":  # scripted pressure on the human client; the Twin plots their delivery against it
            level = max(pressure_for_turn(self._ai_turns), pressure_for_time(self.now()))
            self._ai_turns += 1
            self.pressure.append({"t": self.now(), "level": level})
            hint = PRESSURE_HINTS[level] + ("\n" + hint if hint else "")
            await self.send_json({"type": "pressure", "level": level, "t": self.now()})
        self.brain.pressure_hint = hint
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
            # recording: place the heard audio where playback actually began (falls back to turn start)
            play_off = (player.first_play_at - self.t0) if player.first_play_at is not None else t_ai_start
            self.recorder.add_ai(play_off, audio)
            spoken = " ".join(sentences[:n_started] if cut else sentences).strip()
            if cut and spoken:
                spoken += " —"
            if was_speaking:
                await self.send_json({"type": "speaking", "who": "ai", "state": "end"})
            if spoken.strip(" —"):
                self.brain.add_ai(spoken)
                # the line is stamped when its audio started playing (not when the turn began, which is
                # earlier by the LLM + TTS latency), so report playback and the transcript line up
                t_start = round(play_off, 2)
                t_end = round(play_off + len(audio) / self.settings.sample_rate, 2)
                if self.role == "client":
                    # Baseline analyzes the caller channel: the AI's own audio, with its script as text
                    self.pipe.feed_utterance(audio, t_start, t_end, text=spoken)
                else:
                    await self._emit_unanalyzed("ai", spoken, t_start, t_end)

    # ------------------------------------------------------------------ end

    async def end(self, reason: str = "hangup") -> str | None:
        """Idempotent. Stops audio, flushes analysis, persists the report, sends call_ended."""
        if self._ending:
            await self.ended.wait()
            return self.report_id
        self._ending = True
        self.end_reason = reason
        for t in (self._deferred_task, self._baseline_task):
            if t is not None and not t.done():
                t.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await t
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
        report["pressure"] = self.pressure
        report["behaviour"] = analyse(report, self.pressure, person=self.analyzed_speaker)
        report["audio"] = await self._write_audio(report)
        try:
            save_report(self.settings.reports_dir, report)
            issue_for_report(self.settings.reports_dir, report["id"], self.settings.issuer_key_path)
        except Exception:
            log.exception("could not save report or credential")
            self.col.errors.append("report or credential could not be saved")
        await self.send_json({"type": "call_ended", "reason": reason, "report_id": self.report_id,
                              "reveal": {"role": self.role, "scenario": self.session.scenario,
                                         "persona_label": self.persona.label, "voice": self.session.voice,
                                         "tts": self.tts.name, "summary": self.persona.summary,
                                         "you_vs_baseline": self.you_vs_baseline(),
                                         "interventions": self.interventions, "actions": self.actions}})
        with suppress(Exception):
            await self.pipe.close()
        if self.on_end is not None:
            with suppress(Exception):
                await self.on_end(self)
        self.ended.set()
        return self.report_id

    async def _write_audio(self, report: dict) -> dict | None:
        """Write data/reports/<id>.wav; never raises (failures go to report errors, audio null)."""
        rec = self.recorder
        if not rec.has_audio:
            return None
        rid = report["id"]
        try:
            path = self.settings.reports_dir / f"{rid}.wav"
            dur = await asyncio.to_thread(rec.write_wav, path, float(report["durations"]["call_s"]))
        except Exception as e:
            log.exception("could not write call audio")
            report["errors"].append(f"call audio not saved: {type(e).__name__}: {e}")
            return None
        return {"url": f"/api/report/{rid}/audio", "duration_s": dur,
                "channels": {"left": "ai", "right": "visitor" if rec.mic else None}}

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
            "interventions": self.interventions,
            "actions": self.actions,
            "suspicion": {"t": self.suspect_t},
            "you_vs_baseline": self.you_vs_baseline(),
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
            "audio": None,  # filled in end() once the WAV is written
            "behaviour": self._behaviour_summary(),
            "errors": self.col.errors,
        }

    def _behaviour_summary(self) -> dict | None:
        try:
            return session_signals.analyse({"transcript": self.col.transcript, "signals": self.col.signals},
                                           self.pressure, person=self.analyzed_speaker)
        except Exception:  # noqa: BLE001
            log.debug("behaviour summary failed", exc_info=True)
            return None
