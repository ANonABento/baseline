"""Public "try it live" API: lobby config, session creation, the live-call WebSocket, reports.

    GET  /api/config                 lobby options + queue/TTS/LLM status
    POST /api/session                {role, scenario, voice, record_audio?} -> {session_id, ws_url}
    WS   /ws/session/{session_id}    queue -> call; contract in backend/README.md "Live call API"
    GET  /api/report/{id}            full end-of-call report (data/reports/<id>.json)
    GET  /api/report/{id}/audio      call recording WAV (data/reports/<id>.wav), Range-capable
    GET  /api/credential/{id}        signed Ed25519 did:key credential for a candidate-role call
    GET  /api/reports?limit=20       newest report summaries

`LiveService` holds the process-wide pieces (session manager, TTS, STT, brain factory). Tests
swap them via `configure(...)`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Callable
from contextlib import suppress

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from caller.brain import BrainFactory
from caller.live_call import LiveCall
from caller.personas import CUSTOMER, ROLES, SCENARIOS, build_persona, normalize_role, scenarios_for
from caller.report import list_reports, load_report, valid_report_id
from caller.tts import TTSProvider, caller_voice, make_tts
from credential import issuer_did, load_credential
from detectors.prosody import ProsodyDetector
from ml import voiceprints
from pipeline import CallPipeline
from providers import make_stt
from segmenter import make_segmenter
from sessions import SessionManager
from settings import Settings, get_settings

log = logging.getLogger("baseline.live")

ALL_ROLES = [*ROLES, "candidate"]  # "random" picks from ROLES only: candidate is the assessment mode

router = APIRouter()


class LiveService:
    def __init__(self, settings: Settings, *, tts: TTSProvider | None = None, stt=None,
                 brain_factory: Callable | None = None, pipeline_factory: Callable | None = None,
                 segmenter_factory: Callable | None = None, manager: SessionManager | None = None):
        self.settings = settings
        self.tts = tts or make_tts(settings)
        self._stt = stt
        self.brains = brain_factory or BrainFactory(settings)
        self.pipeline_factory = pipeline_factory or self._default_pipeline
        self.segmenter_factory = segmenter_factory or (lambda: make_segmenter(settings))
        self.manager = manager or SessionManager(
            settings.max_concurrent_calls, settings.max_call_seconds, reconnect_grace_s=settings.reconnect_grace_s,
            idle_timeout_s=settings.session_idle_timeout_s, default_call_s=settings.default_call_estimate_s)
        self.calls: dict[str, LiveCall] = {}
        log.info("live calls: tts=%s (%d voices), persona llm=%s, max_concurrent=%d, max_call_s=%d",
                 self.tts.name, len(self.tts.voices()), self.llm_info(), self.manager.max_concurrent,
                 int(settings.max_call_seconds))

    def _default_pipeline(self, emit, role: str = "agent") -> CallPipeline:
        # candidate: only delivery signals on the trainee's voice (no spoof/speaker/fraud scoring of the trainee)
        dets = [ProsodyDetector()] if role == "candidate" else None
        return CallPipeline(emit, self.settings, detectors=dets)

    @property
    def stt(self):
        if self._stt is None:
            self._stt = make_stt(self.settings)
        return self._stt

    def llm_info(self) -> dict:
        info = getattr(self.brains, "info", None)
        return info() if callable(info) else {"provider": getattr(self.brains, "name", "custom"), "model": None}

    def customer_enrolled(self) -> bool:
        return voiceprints.load(self.settings.enroll_dir, CUSTOMER.id) is not None


_service: LiveService | None = None


def service() -> LiveService:
    global _service
    if _service is None:
        _service = LiveService(get_settings())
    return _service


def configure(svc: LiveService | None) -> None:
    """Install a LiveService (tests); None resets to lazy default construction."""
    global _service
    _service = svc


async def warmup_live(settings: Settings) -> None:
    """Pre-spawn TTS and load the persona LLM's prompt so the first call starts fast."""
    svc = service()
    from ml import segnet
    if segnet.enabled():  # load the fine-tuned model now, not during the first turn
        with suppress(Exception):
            await asyncio.to_thread(segnet.load)
    warm = getattr(svc.tts, "warm", None)
    if warm is not None:
        with suppress(Exception):
            await warm(svc.tts.default_voice())
    if getattr(svc.brains, "provider", "stub") != "stub":
        try:
            brain = svc.brains(build_persona("client", "fake_bank"))
            brain.add_ai(build_persona("client", "fake_bank").openers[0])
            brain.add_visitor("Hello, how can I help?")
            async for _ in brain.reply():
                pass
            err = getattr(brain, "last_error", None)
            log.info("persona LLM %s", f"warmup incomplete ({err}); first reply may be slow" if err else "warm")
        except Exception:
            log.warning("persona LLM warmup failed", exc_info=True)


# ---------------------------------------------------------------------------- HTTP

@router.get("/api/config")
async def api_config() -> dict:
    svc = service()
    return {
        "roles": ALL_ROLES,
        "scenarios": [{"id": s.id, "label": s.label, "role": s.role, "brief": s.brief} for s in SCENARIOS.values()],
        "customer": {"id": CUSTOMER.id, "name": CUSTOMER.name, "account_mask": CUSTOMER.account_mask},
        "voices": svc.tts.voices(),
        "max_concurrent": svc.manager.max_concurrent,
        "queue_length": svc.manager.queue_length,
        "active_calls": svc.manager.active_calls,
        "tts": svc.tts.name,
        "llm": svc.llm_info(),
        "caller_llm": svc.llm_info(),
    }


class SessionRequest(BaseModel):
    role: str = "random"
    scenario: str = "random"
    voice: str = "random"
    record_audio: bool = False  # also record the visitor's mic (right channel of the report WAV)


def _pick(value: str, options: list[str], what: str) -> str:
    v = (value or "random").strip()
    if v == "random":
        return random.choice(options)
    if v not in options:
        raise HTTPException(400, f"unknown {what}: {v!r}; expected one of {options + ['random']}")
    return v


@router.post("/api/session")
async def api_session(req: SessionRequest, request: Request) -> dict:
    svc = service()
    role = _pick(normalize_role((req.role or "random").strip()), list(ALL_ROLES) if (req.role or "").strip() == "candidate" else list(ROLES), "role")
    sc_req = (req.scenario or "random").strip()
    if sc_req != "random" and sc_req in SCENARIOS and SCENARIOS[sc_req].role != role:
        if req.role in ("random", "", None):  # a scenario implies its role
            role = SCENARIOS[sc_req].role
        else:
            raise HTTPException(400, f"scenario {sc_req!r} belongs to role {SCENARIOS[sc_req].role!r}, not {role!r}")
    scenario = _pick(sc_req, list(scenarios_for(role)), "scenario")
    if (req.voice or "random").strip() == "random":
        voice = caller_voice(svc.tts, svc.settings, clone=bool(SCENARIOS[scenario].clone_voice))
    else:
        voice = _pick(req.voice, [v["id"] for v in svc.tts.voices()], "voice")
    s = svc.manager.create(role, scenario, voice, requested=req.model_dump())
    base = str(request.base_url).rstrip("/")
    ws_base = "wss://" + base[len("https://"):] if base.startswith("https://") else "ws://" + base.split("://", 1)[-1]
    return {"session_id": s.id, "ws_url": f"{ws_base}/ws/session/{s.id}"}


@router.get("/api/report/{report_id}")
async def api_report(report_id: str) -> dict:
    r = load_report(service().settings.reports_dir, report_id)
    if r is None:
        raise HTTPException(404, "report not found")
    return r


@router.get("/api/report/{report_id}/audio")
async def api_report_audio(report_id: str) -> FileResponse:
    if not valid_report_id(report_id):
        raise HTTPException(404, "audio not found")
    path = service().settings.reports_dir / f"{report_id}.wav"
    if not path.is_file():
        raise HTTPException(404, "audio not found")
    return FileResponse(path, media_type="audio/wav")


@router.get("/api/issuer")
async def api_issuer() -> dict:
    """The issuer did:key. Compare it with the `issuer` field of a credential to pin who signed it."""
    return {"issuer": issuer_did(service().settings.issuer_key_path)}


@router.get("/api/credential/{report_id}")
async def api_credential(report_id: str) -> dict:
    """Signed simulation credential (candidate role only). Verify offline: /verify.html or scripts/credential.py."""
    c = load_credential(service().settings.reports_dir, report_id)
    if c is None:
        raise HTTPException(404, "credential not found")
    return c


@router.get("/api/reports")
async def api_reports(limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    return list_reports(service().settings.reports_dir, limit)


# ---------------------------------------------------------------------------- WebSocket

class _Conn:
    """Serializes all sends on one WebSocket (JSON + binary)."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.lock = asyncio.Lock()
        self.open = True

    async def send_json(self, msg: dict) -> None:
        if not self.open:
            return
        async with self.lock:
            try:
                await self.ws.send_text(json.dumps(msg))
            except Exception:
                self.open = False
                raise

    async def send_bytes(self, data: bytes) -> None:
        if not self.open:
            return
        async with self.lock:
            try:
                await self.ws.send_bytes(data)
            except Exception:
                self.open = False
                raise


def _parse(msg: dict) -> dict | None:
    try:
        data = json.loads(msg["text"])
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


@router.websocket("/ws/session/{session_id}")
async def ws_session(ws: WebSocket, session_id: str) -> None:
    svc = service()
    mgr = svc.manager
    await ws.accept()
    conn = _Conn(ws)
    try:
        sess = await mgr.attach(session_id, conn.send_json)
    except KeyError:
        await conn.send_json({"type": "error", "message": "unknown or expired session; create a new one"})
        await ws.close(code=4404)
        return
    except RuntimeError as e:
        await conn.send_json({"type": "error", "message": str(e)})
        await ws.close(code=4409)
        return
    seq = sess.attach_seq
    if sess.promoted.is_set():  # no wait: still tell the client the queue is behind it (position 0)
        await conn.send_json({"type": "queue", "position": 0, "queue_length": mgr.queue_length, "eta_s": 0})
    call: LiveCall | None = None
    receiver_closed = False
    try:
        # ---- waiting in the queue: listen for hangup/ping/disconnect until promoted
        while not sess.promoted.is_set():
            recv = asyncio.create_task(ws.receive())
            prom = asyncio.create_task(sess.promoted.wait())
            done, _ = await asyncio.wait({recv, prom}, return_when=asyncio.FIRST_COMPLETED)
            if recv not in done:
                recv.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await recv
                break
            prom.cancel()
            msg = recv.result()
            if msg["type"] == "websocket.disconnect":
                receiver_closed = True
                return
            data = _parse(msg) if msg.get("text") is not None else None
            if data is None:
                continue  # mic audio before the call starts is ignored
            if data.get("type") == "hangup":
                await mgr.remove(session_id)
                await ws.close()
                receiver_closed = True
                return
            if data.get("type") == "ping":
                await conn.send_json(mgr.queue_event(session_id) | {"type": "queue"})

        # ---- active call
        persona = build_persona(sess.role, sess.scenario)

        async def on_end(_c: LiveCall) -> None:
            svc.calls.pop(session_id, None)
            await mgr.finish(session_id)

        call = LiveCall(session=sess, settings=svc.settings, send_json=conn.send_json, send_bytes=conn.send_bytes,
                        persona=persona, brain=svc.brains(persona), tts=svc.tts, stt=svc.stt,
                        pipeline=svc.pipeline_factory(lambda ev: asyncio.sleep(0), sess.role),
                        segmenter=svc.segmenter_factory(), customer_enrolled=svc.customer_enrolled(),
                        llm_info=svc.llm_info(), on_end=on_end)
        svc.calls[session_id] = call
        await call.start()
        ended = asyncio.create_task(call.wait())
        while not call.ended.is_set():
            recv = asyncio.create_task(ws.receive())
            done, _ = await asyncio.wait({recv, ended}, return_when=asyncio.FIRST_COMPLETED)
            if recv not in done:
                recv.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await recv
                break
            msg = recv.result()
            if msg["type"] == "websocket.disconnect":
                receiver_closed = True
                await call.end("hangup")
                break
            if msg.get("bytes") is not None:
                call.feed_mic(msg["bytes"])
                continue
            data = _parse(msg) if msg.get("text") is not None else None
            if data is None:
                await conn.send_json({"type": "error", "message": "text frames must be JSON objects"})
                continue
            kind = data.get("type")
            if kind == "hangup":
                await call.end("hangup")
            elif kind == "ping":
                await conn.send_json({"type": "pong"})
            elif kind == "text":
                await call.feed_text(str(data.get("text", "")))
            elif kind == "suspect":
                await call.suspect()
            elif kind == "ptt":
                call.ptt(str(data.get("state", "")))
            else:
                await conn.send_json({"type": "error", "message": f"unknown message type: {kind!r}"})
    except WebSocketDisconnect:
        receiver_closed = True
        if call is not None:
            await call.end("hangup")
    except Exception as e:
        log.exception("live session %s failed", session_id)
        with suppress(Exception):
            await conn.send_json({"type": "error", "message": f"server error: {type(e).__name__}"})
        if call is not None:
            await call.end("error")
    finally:
        conn.open = conn.open and not receiver_closed
        if call is None:
            await mgr.detach(session_id, seq)  # queued: keeps the place for the grace period
        elif not call.ended.is_set():
            await call.end("hangup")
        if not receiver_closed:
            with suppress(Exception):
                await ws.close()
