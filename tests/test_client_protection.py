"""Client protection (role client): client-side risk rules, soft-signal fusion, intervention policy,
and the live WS flow: caution -> intervention -> high -> Baseline's voice + actions -> report."""

from __future__ import annotations

import json

import pytest

from caller.intervention import MESSAGES, InterventionPolicy, candidates
from detectors.client_risk import assess
from events import DetectorResult
from fusion import Fusion

ASK_CODE = ["We just texted you a six-digit code. Can you read me that code?"]


@pytest.mark.parametrize("text,ctx,reason", [
    ("Okay, the code is 4 8 2 9 1 7", [], "share_code"),
    ("482917", ASK_CODE, "reading_digits"),
    ("four eight two nine one seven", ASK_CODE, "reading_digits"),
    ("Hold on, let me get my card", [], "get_card"),
    ("My card number is 4111 1111 1111 1111", [], "share_card"),
    ("My PIN is 1234", [], "share_pin"),
    ("my social security number is", [], "share_ssn"),
    ("Which store should I go to?", [], "gift_cards"),
    ("I won't tell anyone, I promise", [], "secrecy_promise"),
    ("Okay, I'll go to the bank right now", [], "go_to_bank"),
    ("Fine, I'll send it", [], "send_money"),
    ("Okay I'm installing AnyDesk on my computer", [], "install_remote"),
])
def test_client_risk_flags(text, ctx, reason):
    r = assess(text, ctx)
    assert r.signal == "client" and r.details["reason_id"] == reason
    assert r.score >= 0.5 and r.confidence >= 0.5
    assert r.details["kind"] == ("secret" if reason.startswith(("share", "reading", "get_card")) else "compliance")


@pytest.mark.parametrize("text,ctx", [
    ("No. I'll hang up and call the bank myself.", ASK_CODE),
    ("Who is this?", ASK_CODE),
    ("Hello?", []),
    ("I'm 72 years old and I live alone", []),
    ("Call me back at 5", []),
])
def test_client_risk_quiet_on_safe_lines(text, ctx):
    r = assess(text, ctx)
    assert r.score < 0.5 and r.details["reason_id"] is None


def _sig(name, score, conf=0.8, **details):
    return DetectorResult(signal=name, score=score, confidence=conf, reason=f"{name} reason", details=details)


def test_client_signal_is_soft():
    f = Fusion()
    f.update(_sig("client", 0.9, reason_id="share_code", kind="secret"))
    assert f.compute_level() == "caution"  # alone: never high
    f.update(_sig("prosody", 0.9))
    assert f.compute_level() == "caution"  # soft + soft: still caution
    f.update(_sig("fraud", 0.9))
    assert f.compute_level() == "high"  # soft client + one hard caller signal
    ev = f.alert_event()
    assert "client" in ev.signals and any(r.startswith("You:") for r in ev.reasons)


def test_one_hard_signal_alone_is_caution():
    f = Fusion()
    f.update(_sig("fraud", 0.9))
    assert f.compute_level() == "caution"


def test_intervention_candidates():
    assert candidates(["safe_account"], None, None, "fake_bank", ["fraud"])[0] == "safe_account"
    assert candidates(["otp_redirect"], None, None, "fake_bank", ["fraud"])[0] == "secret_request"
    assert candidates([], "secret", "share_code", "fake_bank", ["client"])[0] == "secret_request"
    assert candidates(["gift_cards"], "secret", "reading_digits", "grandchild", ["fraud"])[0] == "gift_cards"
    assert "voice_clone" in candidates(["grandparent_bail"], None, None, "grandchild", ["fraud"])
    assert candidates([], None, None, "irs", ["spoof"]) == ["generic"]
    assert all(len(m.split()) <= 26 for m in MESSAGES.values())


def test_intervention_policy_throttle():
    p = InterventionPolicy(min_gap_s=10)
    d = p.decide("caution", ["voice_clone", "generic"], 5.0)
    assert d.reason_id == "voice_clone"
    p.record("caution", d.reason_id, 5.0)
    assert p.decide("caution", ["voice_clone", "generic"], 6.0).reason_id is None  # nothing new
    d = p.decide("caution", ["gift_cards", "voice_clone", "generic"], 8.0)  # new reason, too soon
    assert d.reason_id is None and d.defer_s == pytest.approx(7.0)
    d = p.decide("high", ["gift_cards", "voice_clone"], 9.0)  # escalation: immediate
    assert d.reason_id == "gift_cards"
    p.record("high", "gift_cards", 9.0)
    assert p.decide("high", ["gift_cards", "voice_clone"], 30.0).reason_id is None
    d = p.decide("high", ["secret_request", "gift_cards"], 30.0)
    assert d.reason_id == "secret_request"
    assert p.decide("none", ["generic"], 40.0).reason_id is None


# ----------------------------------------------------------------------------- live WS flow

from test_live import jsons, make_client, new_session, recv_until  # noqa: E402


def test_role_client_intervention_flow(tmp_path):
    client, svc = make_client(tmp_path, intervention_min_gap_s=10)
    with client:
        sid = new_session(client, role="client", scenario="fake_bank", voice="stub-a")
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            recv_until(ws, lambda m: m["type"] == "call_started")
            # opener: "...the First Harbor fraud department... flagged a suspicious charge" -> fraud -> caution
            seen = recv_until(ws, lambda m: m["type"] == "intervention")
            iv = jsons(seen, "intervention")[0]
            assert iv["level"] == "caution" and iv["reason_id"] and iv["message"].startswith("This is Baseline")
            assert not jsons(seen, "baseline_audio_start")  # caution: no voice
            ws.send_text(json.dumps({"type": "suspect"}))
            ack = recv_until(ws, lambda m: m["type"] == "suspect_ack")[-1]
            assert ack["t"] is not None and ack["t"] > 0
            # the client starts reading the code: soft client signal + hard fraud -> high
            ws.send_text(json.dumps({"type": "text", "text": "Okay, the code is 4 8 2 9 1 7"}))
            seen = recv_until(ws, lambda m: m["type"] == "baseline_audio_end")
            sig = [m for m in jsons(seen, "signal") if m["signal"] == "client"]
            assert sig and sig[0]["score"] >= 0.5 and sig[0]["utterance_id"] >= 1000
            assert any(m["level"] == "high" for m in jsons(seen, "alert"))
            hi = [m for m in jsons(seen, "intervention") if m["level"] == "high"]
            assert hi and hi[0]["reason_id"] == "secret_request"
            kinds = [m["kind"] for m in jsons(seen, "action")]
            assert kinds == ["family_alert", "bank_hold"]
            i0 = next(i for i, m in enumerate(seen) if isinstance(m, dict) and m["type"] == "baseline_audio_start")
            frames = [m for m in seen[i0:] if isinstance(m, bytes)]
            assert frames  # Baseline's voice, between start and end markers
            ws.send_text(json.dumps({"type": "hangup"}))
            seen = recv_until(ws, lambda m: m["type"] == "call_ended")
            end = jsons(seen, "call_ended")[0]
            yvb = end["reveal"]["you_vs_baseline"]
            assert yvb["visitor_flag_t"] == ack["t"] and yvb["baseline_flag_t"] is not None
            assert yvb["actions"] == ["family_alert", "bank_hold"]
        r = client.get(f"/api/report/{sid}").json()
        assert [i["level"] for i in r["interventions"]][:2] == ["caution", "high"]
        assert r["interventions"][1]["spoken"] is True and r["interventions"][0]["spoken"] is False
        assert [a["kind"] for a in r["actions"]] == ["family_alert", "bank_hold"]
        assert r["suspicion"]["t"] == ack["t"]
        assert r["verdict"]["level"] == "high"
        # Baseline's warning never reaches the fraudster: not in the transcript the AI saw
        assert not any("Baseline" in x["text"] for x in r["transcript"])


def test_role_scammer_gets_no_interventions(tmp_path):
    client, svc = make_client(tmp_path)
    with client:
        sid = new_session(client, role="scammer", scenario="account_takeover", voice="stub-a")
        with client.websocket_connect(f"/ws/session/{sid}") as ws:
            recv_until(ws, lambda m: m["type"] == "call_started")
            ws.send_text(json.dumps({"type": "text", "text": "This is Kevin. I lost my phone, change my number and "
                                     "wire nine thousand dollars today, it's urgent."}))
            seen = recv_until(ws, lambda m: m["type"] == "alert")
            ws.send_text(json.dumps({"type": "hangup"}))
            seen += recv_until(ws, lambda m: m["type"] == "call_ended")
            assert not jsons(seen, "intervention") and not jsons(seen, "action")


@pytest.fixture(autouse=True)
def _reset_service():
    yield
    import live_api

    live_api.configure(None)
