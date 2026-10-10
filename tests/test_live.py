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
from caller.personas import CLIENT_SCENARIOS, SCAMMER_SCENARIOS, SCENARIOS, build_persona, clean_line, split_sentences
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


@pytest.mark.parametrize("scenario", list(CLIENT_SCENARIOS))
def test_fraudster_persona_prompt(scenario):
    p = build_persona("client", scenario)
    assert build_persona("agent", scenario) == p  # deprecated alias
    sp = p.system_prompt
    assert "AUTHORIZED FRAUD-TRAINING SIMULATION" in sp
    assert "Ethan" in sp and SCENARIOS[scenario].goals in sp and "Margaret" not in sp
    assert "two short sentences" in sp and "never break character" in sp
    assert p.openers and p.stub_lines and p.summary
    assert p.label.startswith("AI fraudster")
    assert p.role == "client"


def test_grandchild_persona_addresses_the_grandparent():
    p = build_persona("client", "grandchild")
    assert "GRANDPARENT" in p.system_prompt and "Grandma" in p.system_prompt
    assert CLIENT_SCENARIOS["grandchild"].claims_customer and CLIENT_SCENARIOS["grandchild"].clone_voice
    assert not CLIENT_SCENARIOS["fake_bank"].claims_customer
    assert all(s.role == "scammer" for s in SCAMMER_SCENARIOS.values())


def test_scammer_role_ai_is_a_victim_with_an_agenda():
    from caller.personas import VICTIMS, agenda_for, victim_for

    for sid, sc in SCAMMER_SCENARIOS.items():
        p = build_persona("scammer", sid)
        v = victim_for(sid)
        assert sc.target in VICTIMS and v.profile in p.system_prompt and "Jordan" not in p.system_prompt
        assert "WARNINGS" in p.system_prompt and p.opener().startswith(("Hello", "Yes"))
        a = agenda_for(sid)
        assert a["target"]["name"] == v.name and a["goal"] and a["steps"] and a["lines"] and a["objections"]
    assert agenda_for("fake_bank") is None
    slow = [s for s in CLIENT_SCENARIOS.values() if s.pace == "slow"]
    assert len(slow) >= 3 and all(s.phases and len(s.stub_lines) >= 8 for s in slow)
    assert "SLOW, patient con" in build_persona("client", "fraud_dept_slow").system_prompt
    with pytest.raises(ValueError):
        build_persona("nobody", "x")


def test_clean_line_and_sentence_split():
    assert clean_line('Ethan: *sighs* "Okay. Two. Three."') == "Okay. Two."
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
    assert parse_voice_list("Ethan (clone):abc, Daniel:def,  ,ghi") == [
        {"id": "abc", "label": "Ethan (clone)"}, {"id": "def", "label": "Daniel"}, {"id": "ghi", "label": "ghi"}]
    t = make_tts(Settings(elevenlabs_api_key="k", elevenlabs_voices="A:abc,B:def", elevenlabs_voice_id="def"))
    assert [v["id"] for v in t.voices()][:2] == ["def", "abc"] and t.default_voice() == "def"
    assert "CwhRBWXzGAHq8TQ4Fs17" in [v["id"] for v in t.voices()]  # stock caller voices stay available
    assert t.valid_voice("EXAVITQu4vr4xnSDxMaL") and "EXAVITQu4vr4xnSDxMaL" not in [v["id"] for v in t.voices()]
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
        assert c["roles"] == ["client", "scammer", "candidate"]
        assert {s["id"] for s in c["scenarios"]} == set(SCENARIOS)
        assert all(set(s) == {"id", "label", "role", "brief"} for s in c["scenarios"])
        assert c["customer"]["name"] == "Ethan"
        assert {s["id"] for s in c["scenarios"] if s["role"] == "client"} == {"fake_bank", "grandchild", "irs",
                                                                              "tech_support", "fraud_dept_slow",
                                                                              "bank_investigation", "amazon_refund"}
        assert c["voices"] == svc.tts.voices()
        assert c["max_concurrent"] == 1 and c["queue_length"] == 0 and c["active_calls"] == 0
        assert c["tts"] == "stub" and set(c["llm"]) == {"provider", "model"}
        assert client.post("/api/session", json={"role": "pilot"}).status_code == 400
        assert client.post("/api/session", json={"scenario": "nope"}).status_code == 400
        assert client.post("/api/session", json={"voice": "nope"}).status_code == 400
        assert client.post("/api/session", json={"role": "scammer", "scenario": "grandchild"}).status_code == 400
        sid = new_session(client)  # all random
        s = svc.manager.get(sid)
        assert s.role in ("client", "scammer") and SCENARIOS[s.scenario].role == s.role
        s = svc.manager.get(new_session(client, role="agent"))  # deprecated alias
        assert s.role == "client" and s.scenario in CLIENT_SCENARIOS
        s = svc.manager.get(new_session(client, scenario="grandchild"))  # scenario implies the role
        assert s.role == "client"
        assert client.get("/api/report/does-not-exist").status_code == 404


def test_role_client_full_call_contract(tmp_path):
    client, svc = make_client(tmp_path)
    with client:
        sid = new_session(client, role="client", scenario="fake_bank", voice="stub-a")
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            seen = recv_until(ws, lambda m: m["type"] == "call_started")
            q = jsons(seen, "queue")
            assert q and set(q[0]) == {"type", "position", "queue_length", "eta_s"}
            cs = jsons(seen, "call_started")[0]
            assert cs["session_id"] == sid and cs["role"] == "client" and cs["scenario"] == "fake_bank"
            assert cs["visitor_as"] == "Ethan" and cs["scenario_label"]
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
            assert t["analyzed"] is True and "Ethan" in t["text"] and t["utterance_id"] == 0
            assert all(0 <= m["rms"] <= 1 for m in jsons(seen, "ai_level"))
            seen = recv_until(ws, lambda m: m["type"] == "trust")
            sigs = {m["signal"] for m in jsons(seen, "signal")}
            assert sigs >= {"fraud", "spoof"} and "speaker" not in sigs  # the caller doesn't claim to be Ethan

            # typed visitor turn -> unanalyzed transcript -> AI replies (analyzed)
            ws.send_text(json.dumps({"type": "text", "text": "Sure. Can you confirm your date of birth?"}))
            seen = recv_until(ws, lambda m: m["type"] == "transcript" and m.get("speaker") == "ai")
            vis = [m for m in jsons(seen, "transcript") if m["speaker"] == "visitor"]
            assert vis and vis[0]["analyzed"] is False and vis[0]["utterance_id"] >= 1000
            ws.send_text(json.dumps({"type": "text", "text": "Okay, what else?"}))
            seen = recv_until(ws, lambda m: m["type"] == "transcript" and m.get("speaker") == "ai")
            ws.send_text(json.dumps({"type": "ping"}))
            ws.send_text(json.dumps({"type": "hangup"}))
            seen = recv_until(ws, lambda m: m["type"] == "call_ended")
            end = jsons(seen, "call_ended")[0]
            assert end["reason"] == "hangup" and end["report_id"] == sid
            assert set(end["reveal"]) >= {"role", "scenario", "persona_label", "voice", "tts", "summary",
                                          "you_vs_baseline", "interventions", "actions"}
            assert end["reveal"]["tts"] == "stub" and end["reveal"]["scenario"] == "fake_bank"

        r = client.get(f"/api/report/{sid}").json()
        assert set(r) >= {"id", "created_at", "ended_reason", "meta", "durations", "transcript", "signals", "trust",
                          "alerts", "verdict", "fraud_evidence", "latencies", "errors"}
        assert r["meta"]["role"] == "client" and r["meta"]["analyzed_channel"] == "ai"
        assert set(r) >= {"interventions", "actions", "suspicion", "you_vs_baseline"}
        assert r["meta"]["persona"]["label"].startswith("AI fraudster")
        assert {x["speaker"] for x in r["transcript"]} == {"ai", "visitor"}
        assert r["verdict"]["level"] in ("caution", "high") and r["verdict"]["caught"] is True
        assert r["fraud_evidence"] and r["alerts"]
        assert r["latencies"]["turns"] and r["latencies"]["turns"][0]["visitor_end_to_first_audio_ms"] is not None
        assert r["durations"]["call_s"] > 0
        lst = client.get("/api/reports?limit=5").json()
        assert lst[0]["id"] == sid and lst[0]["role"] == "client"
        assert svc.manager.active_calls == 0


def test_role_scammer_text_is_analyzed(tmp_path):
    client, svc = make_client(tmp_path)
    with client:
        sid = new_session(client, role="scammer", scenario="random", voice="random")
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            recv_until(ws, lambda m: m["type"] == "call_started")
            seen = recv_until(ws, lambda m: m["type"] == "transcript")
            ai = jsons(seen, "transcript")[0]
            assert ai["speaker"] == "ai" and ai["analyzed"] is False and ai["text"]
            ws.send_text(json.dumps({"type": "text", "text": "This is Ethan. I lost my phone, please change "
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


def test_role_client_mic_audio_goes_through_stt(tmp_path):
    client, svc = make_client(tmp_path)
    with client:
        sid = new_session(client, role="client", scenario="irs", voice="stub-b")
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


def _read_wav(data: bytes):
    import io
    import wave
    with wave.open(io.BytesIO(data), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, w.getnchannels())
        return w.getnchannels(), w.getframerate(), w.getsampwidth(), x


@pytest.mark.parametrize("record", [True, False])
def test_call_audio_recording(tmp_path, record):
    client, svc = make_client(tmp_path)
    with client:
        assert client.get("/api/report/does-not-exist/audio").status_code == 404
        assert client.get("/api/report/bad..id/audio").status_code == 404
        sid = new_session(client, role="client", scenario="fake_bank", voice="stub-b", record_audio=record)
        assert svc.manager.get(sid).requested["record_audio"] is record
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            recv_until(ws, lambda m: m["type"] == "speaking" and m["who"] == "ai" and m["state"] == "end")
            for i in range(0, 32000, 3200):
                ws.send_bytes(tone(1.0)[i:i + 3200])
            for _ in range(10):
                ws.send_bytes(bytes(3200))
            recv_until(ws, lambda m: m["type"] == "transcript" and m["speaker"] == "visitor")
            ws.send_text(json.dumps({"type": "hangup"}))
            recv_until(ws, lambda m: m["type"] == "call_ended")
        r = client.get(f"/api/report/{sid}").json()
        a = r["audio"]
        assert a is not None and a["url"] == f"/api/report/{sid}/audio"
        assert a["channels"] == {"left": "ai", "right": "visitor" if record else None}
        assert a["duration_s"] >= r["durations"]["call_s"] - 0.05
        assert (tmp_path / "reports" / f"{sid}.wav").is_file()
        res = client.get(a["url"])
        assert res.status_code == 200 and res.headers["content-type"] == "audio/wav"
        ch, sr, width, x = _read_wav(res.content)
        assert (ch, sr, width) == (2, 16000, 2)
        assert abs(len(x) / sr - a["duration_s"]) < 0.01
        assert np.abs(x[:, 0]).max() > 1000  # AI opener on the left
        assert bool(np.abs(x[:, 1]).max() > 1000) is record  # visitor tone on the right only if recorded
        part = client.get(a["url"], headers={"Range": "bytes=0-99"})
        assert part.status_code == 206 and len(part.content) == 100
        assert client.get("/api/reports?limit=5").json()[0]["id"] == sid


def test_call_audio_write_failure_keeps_report(tmp_path, monkeypatch):
    from caller.recording import CallRecorder

    def boom(self, path, duration_s):
        raise OSError("disk full")
    monkeypatch.setattr(CallRecorder, "write_wav", boom)
    client, svc = make_client(tmp_path)
    with client:
        sid = new_session(client, role="client", scenario="fake_bank", voice="stub-b")
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            recv_until(ws, lambda m: m["type"] == "speaking" and m["who"] == "ai" and m["state"] == "end")
            ws.send_text(json.dumps({"type": "hangup"}))
            recv_until(ws, lambda m: m["type"] == "call_ended")
        r = client.get(f"/api/report/{sid}").json()
        assert r["audio"] is None and any("call audio not saved" in e for e in r["errors"])
        assert client.get(f"/api/report/{sid}/audio").status_code == 404


def test_call_recorder_placement(tmp_path):
    from caller.recording import CallRecorder
    rec = CallRecorder(16000, record_visitor=False)
    rec.add_mic(1.0, np.ones(1600, dtype=np.float32))
    assert not rec.has_audio  # visitor audio is dropped unless opted in
    rec.add_ai(0.5, np.full(1600, 0.5, dtype=np.float32))
    dur = rec.write_wav(tmp_path / "x.wav", 1.0)
    ch, sr, _, x = _read_wav((tmp_path / "x.wav").read_bytes())
    assert dur == 1.0 and len(x) == 16000 and ch == 2
    assert x[7999, 0] == 0 and x[8000, 0] > 16000 and x[9600, 0] == 0 and not x[:, 1].any()


def test_role_candidate_signals_pressure_and_credential(tmp_path):
    """The trainee's own voice is analysed (prosody only), the AI applies scripted pressure, the report carries
    `behaviour`, and a verifiable credential is served. Software correctness only, not a validity claim."""
    import credential

    client, svc = make_client(tmp_path)
    with client:
        sid = new_session(client, role="candidate", scenario="pressure_vip_wire", voice="stub-a")
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            assert jsons(recv_until(ws, lambda m: m["type"] == "call_started"), "call_started")[-1]["role"] == "candidate"
            seen = recv_until(ws, lambda m: m["type"] == "speaking" and m["who"] == "ai" and m["state"] == "end")
            assert jsons(seen, "pressure")[0]["level"] == 1
            for i in range(0, 32000, 3200):
                ws.send_bytes(tone(1.0)[i:i + 3200])
            for _ in range(10):
                ws.send_bytes(bytes(3200))
            seen = recv_until(ws, lambda m: m["type"] == "signal" and m["signal"] == "prosody")
            vis = [m for m in jsons(seen, "transcript") if m["speaker"] == "visitor"]
            assert vis and vis[0]["analyzed"] is True  # the candidate is the analysed channel
            ws.send_text(json.dumps({"type": "text", "text": "I can't do that until I verify you, I will call you back on the number on file."}))
            recv_until(ws, lambda m: m["type"] == "transcript" and m["speaker"] == "ai" and m["utterance_id"] >= 1000 and m["text"] != "")
            ws.send_text(json.dumps({"type": "hangup"}))
            seen = recv_until(ws, lambda m: m["type"] == "call_ended")
            assert not [m for m in jsons(seen) if m["type"] in ("alert", "trust")]  # trainee is not fraud-scored
        r = client.get(f"/api/report/{sid}").json()
        assert r["meta"]["analyzed_channel"] == "visitor" and r["pressure"]
        b = r["behaviour"]
        assert b["calibration_status"] == "not_established" and b["n_turns_analysed"] >= 2
        assert {e["event"] for e in b["decision_events"]} >= {"verification_requested"}
        cred = client.get(f"/api/credential/{sid}").json()
        assert credential.verify(cred, r)[0] and cred["payload"]["session_id"] == sid
        r["transcript"][1]["text"] = "edited after signing"
        assert not credential.verify(cred, r)[0]
        assert client.get("/api/credential/does-not-exist").status_code == 404
        assert client.get("/api/issuer").json()["issuer"] == cred["payload"]["issuer"]


def test_candidate_prompt_is_human_and_pressure_aware():
    from caller.brain import StubBrain
    from caller.personas import PRESSURE_HINTS, build_persona

    persona = build_persona("candidate", "pressure_vip_wire")
    assert "real person" in persona.system_prompt and "Dana Whitfield" in persona.system_prompt
    brain = StubBrain(persona)
    brain.pressure_hint = PRESSURE_HINTS[3]
    assert set(PRESSURE_HINTS) == {1, 2, 3} and "LEVEL 3" in PRESSURE_HINTS[3]


def test_spoken_text_normalisation():
    from caller.personas import clean_line

    assert clean_line("Right now.\u202fI\u2019m on my way, call 555\u20110198.") == "Right now. I\u2019m on my way, call 555-0198."


def test_dashes_become_pauses():
    from caller.personas import clean_line

    assert clean_line("I can\u2019t wait\u2014Greg promised it. Call line\u2014no one picks up") == "I can\u2019t wait, Greg promised it. Call line, no one picks up"


def test_decision_tags_operational():
    from detectors.session_signals import decision_tags

    assert "escalated" in decision_tags("Let me escalate this to my supervisor")
    assert "offered_alternative" in decision_tags("What I can do is open a ticket in the meantime")
    assert "overpromised" in decision_tags("I guarantee it will be there by five")


def test_barge_in_stops_ai_audio(tmp_path):
    client, svc = make_client(tmp_path, barge_in_ms=200, audio_lead_ms=100)
    svc.tts = StubTTS(seconds_per_word=0.5, max_seconds=4.0)  # long opener so we can interrupt it
    with client:
        sid = new_session(client, role="client", scenario="fake_bank", voice="stub-a")
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
        a = new_session(client, role="client", scenario="tech_support", voice="stub-a")
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
    p = build_persona("client", "fake_bank")
    out, client, b = await _reply(p, "Alex: Sure thing. I lost my phone yesterday. Third sentence. Fourth.")
    assert out == ["Sure thing.", "I lost my phone yesterday."]
    assert client.kwargs["reasoning_effort"] == "none" and client.kwargs["stream"] is True
    msgs = client.kwargs["messages"]
    assert msgs[0]["role"] == "system" and msgs[1] == {"role": "user", "content": "(call connected)"}
    assert msgs[-1] == {"role": "user", "content": "hello"}


def _redacting_persona():
    import dataclasses

    from caller.personas import CUSTOMER, record_secrets

    return dataclasses.replace(build_persona("client", "fake_bank"), secrets=record_secrets(CUSTOMER),
                               redaction_line="I'm sorry, I can't share details from the account.")


async def test_llm_brain_redacts_bank_record_and_falls_back():
    p = _redacting_persona()
    out, _, _ = await _reply(p, "Sure. Your date of birth is March 14, 1951 on file. Anything else?")
    assert out[0] == p.redaction_line and not any("1951" in x for x in out)
    out, _, b = await _reply(p, "", fail=True)
    assert out == [p.stub_lines[0]] and b.last_error


async def test_llm_brain_first_clause_cut():
    p = _redacting_persona()
    out, _, _ = await _reply(p, "Hello Ethan, I will need your full name, date of birth, ZIP code, and a "
                                "passcode sent to your phone first. Then we can proceed. Extra.")
    assert out[0].endswith(",") and len(out) == 3 and out[2] == "Then we can proceed."


async def test_llm_brain_strips_leaked_reasoning():
    from caller.brain import strip_reasoning

    assert strip_reasoning("analysis The user wants a code.") == ("", True)
    assert strip_reasoning("analysisThe user...assistantfinalHi Ethan, it's Alex.") == ("Hi Ethan, it's Alex.", False)
    assert strip_reasoning("<think>hmm") == ("", True)
    assert strip_reasoning("Plain line.") == ("Plain line.", False)
    p = build_persona("client", "fake_bank")
    out, _, _ = await _reply(p, "analysis We should ask for the code. assistantfinal Hi Ethan. Can you read me the code?")
    assert out == ["Hi Ethan. Can you read me the code?"]


async def test_llm_brain_falls_back_to_ollama_then_script():
    from caller.brain import LLMBrain, LLMRoute

    p = build_persona("client", "irs")
    good = _FakeClient("Officer Ross here. You owe back taxes.")
    b = LLMBrain(p, _FakeClient("", fail=True), "gpt-oss", "nebius", reasoning_effort="low",
                 fallback=LLMRoute(good, "qwen3.5:4b", "ollama", "none", 90), first_timeout_s=2)
    b.add_visitor("hello")
    out = [x async for x in b.reply()]
    assert out == ["Officer Ross here.", "You owe back taxes."] and b.last_route == "ollama"
    assert good.kwargs["reasoning_effort"] == "none"
    b = LLMBrain(p, _FakeClient("", fail=True), "gpt-oss", "nebius",
                 fallback=LLMRoute(_FakeClient("", fail=True), "q", "ollama"))
    b.add_visitor("hello")
    assert [x async for x in b.reply()] == [p.stub_lines[0]] and b.last_route == "stub"


def test_caller_llm_resolution():
    from caller.brain import BrainFactory, caller_provider_name

    assert caller_provider_name(Settings(caller_llm_provider="auto", nebius_api_key="")) == "ollama"
    assert caller_provider_name(Settings(caller_llm_provider="auto", nebius_api_key="k")) == "nebius"
    assert caller_provider_name(Settings(caller_llm_provider="nebius", nebius_api_key="")) == "ollama"
    f = BrainFactory(Settings(caller_llm_provider="auto", nebius_api_key="k"))
    assert f.info()["provider"] == "nebius" and f.info()["model"] == "openai/gpt-oss-120b"
    assert f.info()["fallback"] == {"provider": "ollama", "model": "qwen3.5:4b"}
    assert f.cfg.reasoning_effort == "low"
    f = BrainFactory(Settings(caller_llm_provider="ollama", caller_llm_model="qwen3:8b"))
    assert f.info() == {"provider": "ollama", "model": "qwen3:8b"}


def test_kokoro_split_routes_baseline_voice_to_elevenlabs():
    from caller.tts import ElevenLabsTTS, KokoroTTS, SplitTTS, baseline_voice

    s = Settings(kokoro_url="http://gpu:8880", elevenlabs_api_key="k", tts_provider="auto")
    tts = make_tts(s)
    assert isinstance(tts, SplitTTS) and isinstance(tts.caller, KokoroTTS) and isinstance(tts.baseline, ElevenLabsTTS)
    assert baseline_voice(tts, s) == s.baseline_voice_id
    assert s.baseline_voice_id not in [v["id"] for v in tts.voices()]  # never offered as a caller voice
    assert tts.valid_voice(s.baseline_voice_id)
    assert isinstance(make_tts(Settings(kokoro_url="http://gpu:8880", tts_provider="auto")), KokoroTTS)
