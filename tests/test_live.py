"""Live "try it" calls: queue, sessions, personas, TTS selection, reports and the WS contract.
Fast and model-free: stub STT / persona brain / TTS, energy VAD, stub detectors."""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

import live_api
from caller.brain import StubBrain
from caller.personas import SCENARIOS, build_persona, clean_line, split_sentences
from caller.tts import ElevenLabsTTS, MacSayTTS, StubTTS, make_tts, parse_voice_list
from providers.base import STTProvider
from sessions import SessionManager
from settings import Settings

# ----------------------------------------------------------------------------- session manager


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def mgr(**kw) -> tuple[SessionManager, Clock, dict]:
    clock = Clock()
    kw.setdefault("refresh_s", 0)
    m = SessionManager(clock=clock, **kw)
    inbox: dict[str, list[dict]] = {}
    return m, clock, inbox


def notifier(inbox, sid):
    async def n(msg):
        inbox.setdefault(sid, []).append(msg)
    return n


async def test_queue_fifo_positions_and_promotion():
    m, clock, inbox = mgr(max_concurrent=1, max_call_s=240, default_call_s=100)
    a, b, c = (m.create("agent", "account_takeover", "v") for _ in range(3))
    for s in (a, b, c):
        await m.attach(s.id, notifier(inbox, s.id))
    assert a.state == "active" and a.promoted.is_set()
    assert m.position(b.id) == 1 and m.position(c.id) == 2
    assert inbox[c.id][-1] == {"type": "queue", "position": 2, "queue_length": 2, "eta_s": 200}
    clock.t += 30  # a has been on for 30 s -> ~70 s left
    assert m.eta_s(b.id) == 70 and m.eta_s(c.id) == 170
    await m.finish(a.id)
    assert b.state == "active" and m.position(c.id) == 1
    assert inbox[c.id][-1]["position"] == 1
    assert m.recent_durations[-1] == 30


async def test_eta_uses_measured_call_length_and_multiple_slots():
    m, clock, _ = mgr(max_concurrent=2, max_call_s=240, default_call_s=100)
    m.recent_durations.extend([60, 60])
    ss = [m.create("agent", "x", "v") for _ in range(4)]
    for s in ss:
        await m.attach(s.id, notifier({}, s.id))
    assert m.active_calls == 2 and m.queue_length == 2
    assert m.eta_s(ss[2].id) == 60 and m.eta_s(ss[3].id) == 60
    clock.t += 50
    assert m.eta_s(ss[2].id) == 10


async def test_reconnect_within_grace_keeps_place():
    m, clock, inbox = mgr(max_concurrent=1, reconnect_grace_s=0.2)
    a, b, c = (m.create("agent", "x", "v") for _ in range(3))
    for s in (a, b, c):
        await m.attach(s.id, notifier(inbox, s.id))
    await m.detach(b.id, b.attach_seq)
    await asyncio.sleep(0.05)
    await m.attach(b.id, notifier(inbox, b.id))
    await asyncio.sleep(0.3)  # past the grace: must still be there
    assert m.position(b.id) == 1 and m.position(c.id) == 2


async def test_disconnect_past_grace_leaves_queue_and_absentee_is_skipped():
    m, clock, inbox = mgr(max_concurrent=1, reconnect_grace_s=0.1)
    a, b, c = (m.create("agent", "x", "v") for _ in range(3))
    for s in (a, b, c):
        await m.attach(s.id, notifier(inbox, s.id))
    await m.detach(b.id, b.attach_seq)
    await m.finish(a.id)  # b is away: connected c takes the slot, b keeps the head of the line
    assert c.state == "active" and m.position(b.id) == 1
    await asyncio.sleep(0.2)
    assert m.get(b.id) is None and m.queue_length == 0


async def test_active_disconnect_frees_slot_immediately():
    m, _, inbox = mgr(max_concurrent=1)
    a, b = m.create("agent", "x", "v"), m.create("scammer", "x", "v")
    await m.attach(a.id, notifier(inbox, a.id))
    await m.attach(b.id, notifier(inbox, b.id))
    await m.detach(a.id, a.attach_seq)
    assert a.state == "ended" and b.state == "active" and m.active_calls == 1


async def test_unattached_session_expires_and_bad_attach():
    m, _, _ = mgr(idle_timeout_s=0.05)
    s = m.create("agent", "x", "v")
    await asyncio.sleep(0.15)
    assert m.get(s.id) is None
    with pytest.raises(KeyError):
        await m.attach(s.id, notifier({}, s.id))


# ----------------------------------------------------------------------------- personas


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_fraudster_persona_prompt(scenario):
    p = build_persona("agent", scenario)
    sp = p.system_prompt
    assert "AUTHORIZED FRAUD-TRAINING SIMULATION" in sp
    assert "Margaret Chen" in sp and SCENARIOS[scenario].goals in sp
    assert "two short sentences" in sp and "never break character" in sp
    assert p.openers and p.stub_lines and p.summary
    assert p.label.startswith("AI fraudster")


def test_bank_agent_persona_follows_verification():
    p = build_persona("scammer", "random")
    assert "verify identity" in p.system_prompt and "one-time" in p.system_prompt
    assert "Never reveal record details" in p.system_prompt
    assert "First Harbor Bank" in p.opener()
    with pytest.raises(ValueError):
        build_persona("nobody", "x")


def test_clean_line_and_sentence_split():
    assert clean_line('Margaret: *sighs* "Okay. Two. Three."') == "Okay. Two."
    assert clean_line("<think>hmm</think>Hi there, it's me.") == "Hi there, it's me."
    done, rest = split_sentences("Hi. I lost my phone. And I need")
    assert done == ["Hi. I lost my phone."] and rest == "And I need"


# ----------------------------------------------------------------------------- TTS selection


def test_tts_fallback_selection(monkeypatch):
    import caller.tts as tts

    monkeypatch.setattr(tts, "say_available", lambda: True)
    assert isinstance(make_tts(Settings(elevenlabs_api_key="k")), ElevenLabsTTS)
    assert isinstance(make_tts(Settings(elevenlabs_api_key="")), MacSayTTS)
    assert isinstance(make_tts(Settings(elevenlabs_api_key="k", tts_provider="say")), MacSayTTS)
    assert isinstance(make_tts(Settings(tts_provider="stub", elevenlabs_api_key="k")), StubTTS)
    monkeypatch.setattr(tts, "say_available", lambda: False)
    assert isinstance(make_tts(Settings(elevenlabs_api_key="")), StubTTS)
    el = make_tts(Settings(elevenlabs_api_key="k"))
    assert el.fallback is None


def test_elevenlabs_voice_list():
    assert parse_voice_list("Margaret (clone):abc, Daniel:def,  ,ghi") == [
        {"id": "abc", "label": "Margaret (clone)"}, {"id": "def", "label": "Daniel"}, {"id": "ghi", "label": "ghi"}]
    t = make_tts(Settings(elevenlabs_api_key="k", elevenlabs_voices="A:abc,B:def", elevenlabs_voice_id="def"))
    assert [v["id"] for v in t.voices()] == ["def", "abc"] and t.default_voice() == "def"
    t = make_tts(Settings(elevenlabs_api_key="k", elevenlabs_voices="A:abc,B:def"))
    assert t.default_voice() == "abc"
    t = make_tts(Settings(elevenlabs_api_key="k", elevenlabs_voice_id="zzz"))
    assert t.voices()[0]["id"] == "zzz" and len(t.voices()) > 1


async def test_stub_tts_pcm():
    pcm = await StubTTS(seconds_per_word=0.1).synthesize("one two three", "stub-a")
    assert len(pcm) == int(16000 * 0.3) * 2


# ----------------------------------------------------------------------------- WS contract


class FixedSTT(STTProvider):
    name = "fixed"

    def __init__(self, text="I can help. What is your date of birth?"):
        self.text = text

    async def transcribe(self, utt):
        return self.text


def make_client(tmp_path, **overrides):
    kw = dict(llm_provider="stub", nebius_api_key="", nvidia_api_key="", reports_dir=tmp_path / "reports",
              max_concurrent_calls=1, audio_lead_ms=2000, call_warning_seconds=1, vad_hangover_ms=300)
    kw |= overrides
    s = Settings(**kw)
    svc = live_api.LiveService(s, tts=StubTTS(seconds_per_word=0.02, max_seconds=0.3), stt=FixedSTT(),
                               brain_factory=lambda persona: StubBrain(persona))
    live_api.configure(svc)
    from app import app
    return TestClient(app), svc


@pytest.fixture(autouse=True)
def _reset_service():
    yield
    live_api.configure(None)


def recv_until(ws, pred, limit=500):
    """Collect messages until pred(msg) is true; binary frames come back as bytes."""
    seen = []
    for _ in range(limit):
        m = ws.receive()
        if m.get("bytes") is not None:
            seen.append(m["bytes"])
            continue
        if m.get("text") is None:
            raise AssertionError(f"socket closed: {m}")
        msg = json.loads(m["text"])
        seen.append(msg)
        if pred(msg):
            return seen
    raise AssertionError("message never arrived")


def jsons(seen, typ=None):
    return [m for m in seen if isinstance(m, dict) and (typ is None or m["type"] == typ)]


def new_session(client, **body):
    r = client.post("/api/session", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) == {"session_id", "ws_url"} and d["ws_url"].endswith(f"/ws/session/{d['session_id']}")
    assert d["ws_url"].startswith("ws://")
    return d["session_id"]


def test_config_and_session_validation(tmp_path):
    client, svc = make_client(tmp_path)
    with client:
        c = client.get("/api/config").json()
        assert c["roles"] == ["agent", "scammer"]
        assert {s["id"] for s in c["scenarios"]} == set(SCENARIOS)
        assert all(set(s) == {"id", "label"} for s in c["scenarios"])
        assert c["voices"] == svc.tts.voices()
        assert c["max_concurrent"] == 1 and c["queue_length"] == 0 and c["active_calls"] == 0
        assert c["tts"] == "stub" and set(c["llm"]) == {"provider", "model"}
        assert client.post("/api/session", json={"role": "pilot"}).status_code == 400
        assert client.post("/api/session", json={"scenario": "nope"}).status_code == 400
        assert client.post("/api/session", json={"voice": "nope"}).status_code == 400
        sid = new_session(client)  # all random
        s = svc.manager.get(sid)
        assert s.role in ("agent", "scammer") and s.scenario in SCENARIOS
        assert client.get("/api/report/does-not-exist").status_code == 404


def test_role_agent_full_call_contract(tmp_path):
    client, svc = make_client(tmp_path)
    with client:
        sid = new_session(client, role="agent", scenario="account_takeover", voice="stub-a")
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            seen = recv_until(ws, lambda m: m["type"] == "call_started")
            q = jsons(seen, "queue")
            assert q and set(q[0]) == {"type", "position", "queue_length", "eta_s"}
            cs = jsons(seen, "call_started")[0]
            assert cs["session_id"] == sid and cs["role"] == "agent" and cs["scenario"] == "account_takeover"
            assert cs["voice"] == "stub-a" and cs["max_call_s"] == 240
            assert cs["audio"] == {"sample_rate": 16000, "format": "pcm_s16le"}
            assert set(cs["customer"]) == {"id", "name", "account_mask", "enrolled"}
            assert cs["customer"]["id"] == "CUST-004217"
            # AI speaks first: audio frames, speaking start/end, then its line is analyzed
            seen = recv_until(ws, lambda m: m["type"] == "transcript" and m.get("speaker") == "ai")
            assert any(isinstance(m, bytes) for m in seen)
            assert {"type": "speaking", "who": "ai", "state": "start"} in seen
            assert {"type": "speaking", "who": "ai", "state": "end"} in seen
            t = jsons(seen, "transcript")[-1]
            assert t["analyzed"] is True and "Margaret" in t["text"] and t["utterance_id"] == 0
            assert all(0 <= m["rms"] <= 1 for m in jsons(seen, "ai_level"))
            seen = recv_until(ws, lambda m: m["type"] == "trust")
            assert {m["signal"] for m in jsons(seen, "signal")} >= {"fraud", "speaker", "spoof"}

            # typed visitor turn -> unanalyzed transcript -> AI replies (analyzed)
            ws.send_text(json.dumps({"type": "text", "text": "Sure. Can you confirm your date of birth?"}))
            seen = recv_until(ws, lambda m: m["type"] == "transcript" and m.get("speaker") == "ai")
            vis = [m for m in jsons(seen, "transcript") if m["speaker"] == "visitor"]
            assert vis and vis[0]["analyzed"] is False and vis[0]["utterance_id"] >= 1000
            ws.send_text(json.dumps({"type": "text", "text": "Okay, what else?"}))
            seen = recv_until(ws, lambda m: m["type"] == "alert")
            ws.send_text(json.dumps({"type": "ping"}))
            ws.send_text(json.dumps({"type": "hangup"}))
            seen = recv_until(ws, lambda m: m["type"] == "call_ended")
            end = jsons(seen, "call_ended")[0]
            assert end["reason"] == "hangup" and end["report_id"] == sid
            assert set(end["reveal"]) == {"role", "scenario", "persona_label", "voice", "tts"}
            assert end["reveal"]["tts"] == "stub" and end["reveal"]["scenario"] == "account_takeover"

        r = client.get(f"/api/report/{sid}").json()
        assert set(r) >= {"id", "created_at", "ended_reason", "meta", "durations", "transcript", "signals", "trust",
                          "alerts", "verdict", "fraud_evidence", "latencies", "errors"}
        assert r["meta"]["role"] == "agent" and r["meta"]["analyzed_channel"] == "ai"
        assert r["meta"]["persona"]["label"].startswith("AI fraudster")
        assert {x["speaker"] for x in r["transcript"]} == {"ai", "visitor"}
        assert r["verdict"]["level"] in ("caution", "high") and r["verdict"]["caught"] is True
        assert r["fraud_evidence"] and r["alerts"]
        assert r["latencies"]["turns"] and r["latencies"]["turns"][0]["visitor_end_to_first_audio_ms"] is not None
        assert r["durations"]["call_s"] > 0
        lst = client.get("/api/reports?limit=5").json()
        assert lst[0]["id"] == sid and lst[0]["role"] == "agent"
        assert svc.manager.active_calls == 0


def test_role_scammer_text_is_analyzed(tmp_path):
    client, svc = make_client(tmp_path)
    with client:
        sid = new_session(client, role="scammer", scenario="random", voice="random")
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            recv_until(ws, lambda m: m["type"] == "call_started")
            seen = recv_until(ws, lambda m: m["type"] == "transcript")
            ai = jsons(seen, "transcript")[0]
            assert ai["speaker"] == "ai" and ai["analyzed"] is False and "First Harbor" in ai["text"]
            ws.send_text(json.dumps({"type": "text", "text": "This is Margaret. I lost my phone, please change "
                                     "my phone number and wire nine thousand dollars to my contractor today, it's urgent."}))
            seen = recv_until(ws, lambda m: m["type"] == "alert")
            vis = [m for m in jsons(seen, "transcript") if m["speaker"] == "visitor"]
            assert vis and vis[0]["analyzed"] is True and vis[0]["utterance_id"] == 0
            assert any(m["signal"] == "fraud" and m["score"] >= 0.5 for m in jsons(seen, "signal"))
            seen = recv_until(ws, lambda m: m["type"] == "transcript" and m["speaker"] == "ai")  # AI agent replies
            ws.send_text(json.dumps({"type": "hangup"}))
            recv_until(ws, lambda m: m["type"] == "call_ended")
        r = client.get(f"/api/report/{sid}").json()
        assert r["meta"]["analyzed_channel"] == "visitor" and r["verdict"]["caught"] is True


def tone(seconds, amp=0.3):
    t = np.arange(int(16000 * seconds)) / 16000
    return (amp * np.sin(2 * np.pi * 200 * t) * 32767).astype("<i2").tobytes()


def test_role_agent_mic_audio_goes_through_stt(tmp_path):
    client, svc = make_client(tmp_path)
    with client:
        sid = new_session(client, role="agent", scenario="safe_account", voice="stub-b")
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            recv_until(ws, lambda m: m["type"] == "call_started")
            recv_until(ws, lambda m: m["type"] == "speaking" and m["who"] == "ai" and m["state"] == "end")
            for i in range(0, 32000 * 1, 3200):
                ws.send_bytes(tone(1.0)[i:i + 3200])
            for _ in range(10):
                ws.send_bytes(bytes(3200))
            seen = recv_until(ws, lambda m: m["type"] == "transcript" and m["speaker"] == "visitor")
            assert {"type": "speaking", "who": "visitor", "state": "start"} in seen
            vis = jsons(seen, "transcript")[-1]
            assert vis["text"] == FixedSTT().text and vis["analyzed"] is False and vis["latency_ms"] is not None
            recv_until(ws, lambda m: m["type"] == "transcript" and m["speaker"] == "ai")
            ws.send_text(json.dumps({"type": "hangup"}))
            recv_until(ws, lambda m: m["type"] == "call_ended")
        r = client.get(f"/api/report/{sid}").json()
        assert r["latencies"]["turns"][0]["source"] == "audio"
        assert r["latencies"]["turns"][0]["stt_ms"] is not None


def test_barge_in_stops_ai_audio(tmp_path):
    client, svc = make_client(tmp_path, barge_in_ms=200, audio_lead_ms=100)
    svc.tts = StubTTS(seconds_per_word=0.5, max_seconds=4.0)  # long opener so we can interrupt it
    with client:
        sid = new_session(client, role="agent", scenario="account_takeover", voice="stub-a")
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            recv_until(ws, lambda m: m["type"] == "speaking" and m["who"] == "ai" and m["state"] == "start")
            for i in range(0, 16000, 3200):
                ws.send_bytes(tone(0.5)[i:i + 3200])
            seen = recv_until(ws, lambda m: m["type"] == "stop_audio")
            seen = recv_until(ws, lambda m: m["type"] == "speaking" and m["who"] == "ai" and m["state"] == "end")
            ws.send_text(json.dumps({"type": "hangup"}))
            recv_until(ws, lambda m: m["type"] == "call_ended")


def test_queue_two_clients_and_timeout(tmp_path):
    client, svc = make_client(tmp_path, max_call_seconds=3, call_warning_seconds=1)
    with client:
        a = new_session(client, role="agent", scenario="verification_evasion", voice="stub-a")
        b = new_session(client, role="scammer", scenario="random", voice="stub-b")
        with client.websocket_connect(f"/ws/session/{a}") as wa:
            recv_until(wa, lambda m: m["type"] == "call_started")
            with client.websocket_connect(f"/ws/session/{b}") as wb:
                q = recv_until(wb, lambda m: m["type"] == "queue")[-1]
                assert q["position"] == 1 and q["queue_length"] == 1 and q["eta_s"] > 0
                assert client.get("/api/config").json()["queue_length"] == 1
                seen = recv_until(wa, lambda m: m["type"] == "call_ended")
                w = jsons(seen, "warning")
                assert w and w[0]["seconds_left"] == 1 and w[0]["message"]
                assert jsons(seen, "call_ended")[0]["reason"] == "timeout"
                seen = recv_until(wb, lambda m: m["type"] == "call_started")
                assert jsons(seen, "call_started")[0]["role"] == "scammer"
                wb.send_text(json.dumps({"type": "hangup"}))
                recv_until(wb, lambda m: m["type"] == "call_ended")
        assert client.get(f"/api/report/{a}").json()["ended_reason"] == "timeout"


def test_unknown_session_ws_error(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        with client.websocket_connect("/ws/session/nope1234") as ws:
            m = json.loads(ws.receive()["text"])
            assert m["type"] == "error"


def test_legacy_ws_call_still_works(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        with client.websocket_connect("/ws/call") as ws:
            m = json.loads(ws.receive()["text"])
            assert m["type"] == "status" and m["state"] == "connected"


# ----------------------------------------------------------------------------- persona LLM streaming


class _FakeChunk:
    def __init__(self, t):
        self.choices = [type("C", (), {"delta": type("D", (), {"content": t})()})()]


class _FakeClient:
    """Minimal AsyncOpenAI stand-in: streams `text` word by word."""

    def __init__(self, text, fail=False):
        outer = self

        class Completions:
            async def create(self, **kw):
                outer.kwargs = kw
                if fail:
                    raise RuntimeError("boom")

                async def gen():
                    for w in text.split():
                        yield _FakeChunk(w + " ")
                return gen()

        self.chat = type("Chat", (), {"completions": Completions()})()


async def _reply(persona, text, fail=False):
    from caller.brain import LLMBrain

    client = _FakeClient(text, fail)
    b = LLMBrain(persona, client, "m", "ollama")
    b.add_ai(persona.openers[0])
    b.add_visitor("hello")
    return [x async for x in b.reply()], client, b


async def test_llm_brain_two_sentences_reasoning_off_and_history():
    p = build_persona("agent", "account_takeover")
    out, client, b = await _reply(p, "Margaret: Sure thing. I lost my phone yesterday. Third sentence. Fourth.")
    assert out == ["Sure thing.", "I lost my phone yesterday."]
    assert client.kwargs["reasoning_effort"] == "none" and client.kwargs["stream"] is True
    msgs = client.kwargs["messages"]
    assert msgs[0]["role"] == "system" and msgs[1] == {"role": "user", "content": "(call connected)"}
    assert msgs[-1] == {"role": "user", "content": "hello"}


async def test_llm_brain_redacts_bank_record_and_falls_back():
    p = build_persona("scammer", "random")
    out, _, _ = await _reply(p, "Sure. Your date of birth is March 14, 1951 on file. Anything else?")
    assert out[0] == p.redaction_line and not any("1951" in x for x in out)
    out, _, b = await _reply(p, "", fail=True)
    assert out == [p.stub_lines[0]] and b.last_error


async def test_llm_brain_first_clause_cut():
    p = build_persona("scammer", "random")
    out, _, _ = await _reply(p, "Hello Margaret, I will need your full name, date of birth, ZIP code, and a "
                                "passcode sent to your phone first. Then we can proceed. Extra.")
    assert out[0].endswith(",") and len(out) == 3 and out[2] == "Then we can proceed."
