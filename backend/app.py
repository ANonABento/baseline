"""FastAPI app: health, demo clip listing, replay, and the call WebSocket.

Run:  cd backend && uv run uvicorn app:app --reload --port 8000

WS /ws/call
  client -> server: binary frames = 16 kHz mono int16 little-endian PCM (live mic),
                    text frames = JSON control messages (see events.py).
  server -> client: JSON events (transcript | signal | trust | alert | status).
POST /replay/{clip}  starts a replay of data/demo/<clip> on every connected session.
GET /customers       enrolled voiceprints (data/enroll/*.npy); GET /customer?customer_id=...

Real models (STT_PROVIDER=mlx, VAD_PROVIDER=silero, SPEAKER_PROVIDER=ecapa,
SPOOF_PROVIDER=pretrained|wavlm) are loaded and warmed up once at startup (WARMUP_MODELS).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import soundfile as sf
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from events import Event, StatusEvent
from ml import voiceprints
from pipeline import CallPipeline, float_to_pcm16, load_wav, stt_for_clip, warmup_models
from providers.stt_stub import sidecar_path_for
from settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("baseline")

settings = get_settings()
WARMUP: dict[str, float] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.warmup_models:
        t0 = time.perf_counter()
        log.info("warming up models: %s", settings.providers_summary())
        # blocking loads happen on the models' own threads; the loop just waits for them
        WARMUP.update(await asyncio.to_thread(warmup_models, settings))
        log.info("warmup done in %.1fs: %s", time.perf_counter() - t0, WARMUP)
    yield


app = FastAPI(title="Baseline", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def resolve_clip(clip: str) -> Path:
    """Only plain file names inside demo_dir (no traversal)."""
    name = Path(clip).name
    path = settings.demo_dir / name
    if name != clip or path.suffix.lower() not in {".wav", ".flac"} or not path.is_file():
        raise FileNotFoundError(clip)
    return path


class Session:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.out: asyncio.Queue[dict] = asyncio.Queue()
        self.pipe = CallPipeline(self.emit, settings)
        self.customer_id = settings.customer_id  # customer on the call (whose voiceprint we verify)
        self.replay_task: asyncio.Task | None = None
        self.end_task: asyncio.Task | None = None

    async def emit(self, ev: Event) -> None:
        await self.out.put(ev.model_dump())

    async def sender(self) -> None:
        while True:
            msg = await self.out.get()
            await self.ws.send_text(json.dumps(msg))

    @property
    def replaying(self) -> bool:
        return self.replay_task is not None and not self.replay_task.done()

    async def cancel_replay(self) -> None:
        if self.replaying:
            self.replay_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.replay_task

    async def select_customer(self, customer_id: str) -> bool:
        if not voiceprints.valid_customer_id(customer_id):
            await self.emit(StatusEvent(state="error", message=f"invalid customer id: {customer_id!r}"))
            return False
        self.customer_id = customer_id
        self.pipe.ctx.customer_id = customer_id  # applies to the call in progress too
        vp = voiceprints.load(settings.enroll_dir, customer_id)
        await self.emit(StatusEvent(state="customer_selected",
                                    message=f"{customer_id} ({'enrolled' if vp else 'no voiceprint enrolled'})"))
        return True

    async def start_replay(self, clip: str, customer_id: str = "") -> None:
        await self.cancel_replay()
        if customer_id and not await self.select_customer(customer_id):
            return
        try:
            path = resolve_clip(clip)
        except FileNotFoundError:
            await self.emit(StatusEvent(state="error", message=f"clip not found: {clip}", clip=clip))
            return
        self.replay_task = asyncio.create_task(self._replay(path))

    async def _replay(self, path: Path) -> None:
        stt, hints = stt_for_clip(path, settings, self.pipe.default_stt)
        self.pipe.start_call(customer_id=self.customer_id, stt=stt, stub_hints=hints)
        audio = load_wav(path, settings.sample_rate)
        sr = settings.sample_rate
        await self.emit(StatusEvent(state="replay_started", clip=path.name,
                                    message=f"{len(audio) / sr:.1f}s, transcript={'sidecar' if stt else self.pipe.stt.name}"))
        step = int(sr * settings.replay_chunk_ms / 1000)
        speed = max(settings.replay_speed, 0.01)
        t0 = time.monotonic()
        for i in range(0, len(audio), step):
            # same ingest path as the mic: int16 PCM bytes
            self.pipe.feed_pcm16(float_to_pcm16(audio[i:i + step]))
            target = t0 + (i + step) / sr / speed
            delay = target - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
        await self.pipe.end_call()
        await self.emit(StatusEvent(state="replay_finished", clip=path.name))

    async def end_call(self) -> None:
        await self.cancel_replay()
        await self.pipe.end_call()
        await self.emit(StatusEvent(state="call_ended"))

    async def handle_control(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "replay":
            await self.start_replay(str(msg.get("clip", "")), str(msg.get("customer_id") or ""))
        elif kind in ("start", "reset"):
            await self.cancel_replay()
            if msg.get("customer_id") and not await self.select_customer(str(msg["customer_id"])):
                return
            self.pipe.start_call(customer_id=self.customer_id)
            await self.emit(StatusEvent(state="call_started", message=str(msg.get("source", "mic"))))
        elif kind == "customer":
            await self.select_customer(str(msg.get("customer_id") or ""))
        elif kind == "stop":
            self.end_task = asyncio.create_task(self.end_call())
        elif kind == "ping":
            await self.emit(StatusEvent(state="pong"))
        else:
            await self.emit(StatusEvent(state="error", message=f"unknown control message: {kind}"))


SESSIONS: set[Session] = set()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "stt": settings.stt_provider, "llm": settings.resolved_llm_provider(),
            "providers": settings.providers_summary(), "warmup_s": WARMUP, "sessions": len(SESSIONS)}


@app.get("/customers")
async def customers() -> list[dict]:
    """Customers with an enrolled voiceprint (scripts/enroll.py)."""
    return voiceprints.list_enrolled(settings.enroll_dir)


@app.get("/customer")
async def customer(customer_id: str = Query("", description="defaults to CUSTOMER_ID")) -> dict:
    cid = customer_id or settings.customer_id
    if not voiceprints.valid_customer_id(cid):
        raise HTTPException(400, "invalid customer id")
    vp = voiceprints.load(settings.enroll_dir, cid)
    is_default = cid == settings.customer_id
    name = (vp.name if vp else "") or (settings.customer_name if is_default else cid)
    if vp is not None:
        voiceprint = f"ECAPA voiceprint, {vp.meta.get('n_segments', '?')} segments / {vp.meta.get('audio_s', '?')}s audio"
    else:
        voiceprint = "not enrolled (run scripts/enroll.py)"
    out = {"id": cid, "name": name, "enrolled": vp is not None, "voiceprint": voiceprint,
           "speaker_provider": settings.speaker_provider}
    if is_default:  # demo profile fields (placeholder CRM data)
        out |= {"phone_on_file": "(650) 555-0142", "member_since": "2009", "segment": "Retail / senior"}
    return out


@app.get("/clips")
async def clips() -> list[dict]:
    out = []
    if settings.demo_dir.is_dir():
        for p in sorted(settings.demo_dir.glob("*.wav")):
            try:
                dur = sf.info(str(p)).duration
            except Exception:
                dur = None
            out.append({"name": p.name, "duration_s": round(dur, 1) if dur else None,
                        "has_transcript": sidecar_path_for(p).exists()})
    return out


@app.post("/replay/{clip}")
async def replay(clip: str) -> dict:
    try:
        resolve_clip(clip)
    except FileNotFoundError:
        raise HTTPException(404, f"clip not found: {clip}")
    if not SESSIONS:
        raise HTTPException(409, "no connected /ws/call session to stream into")
    for s in list(SESSIONS):
        await s.start_replay(clip)
    return {"clip": clip, "sessions": len(SESSIONS)}


@app.websocket("/ws/call")
async def ws_call(ws: WebSocket) -> None:
    await ws.accept()
    s = Session(ws)
    SESSIONS.add(s)
    sender = asyncio.create_task(s.sender())
    s.pipe.start_call(customer_id=s.customer_id)
    prov = " ".join(f"{k}={v}" for k, v in settings.providers_summary().items())
    await s.emit(StatusEvent(state="connected", message=prov))
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if not s.replaying:  # ignore mic audio while a replay owns the pipeline
                    s.pipe.feed_pcm16(msg["bytes"])
            elif msg.get("text") is not None:
                try:
                    data = json.loads(msg["text"])
                    if not isinstance(data, dict):
                        raise ValueError
                except ValueError:
                    await s.emit(StatusEvent(state="error", message="control frames must be JSON objects"))
                    continue
                await s.handle_control(data)
    except WebSocketDisconnect:
        pass
    finally:
        SESSIONS.discard(s)
        await s.cancel_replay()
        for t in (s.end_task, sender):
            if t and not t.done():
                t.cancel()
        await s.pipe.close()
