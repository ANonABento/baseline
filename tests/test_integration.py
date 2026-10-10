"""End-to-end: demo WAVs through the real pipeline (stub STT + sidecar transcripts)."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pipeline import analyze_wav
from settings import Settings

DEMO = Path(__file__).resolve().parent.parent / "data" / "demo"
pytestmark = pytest.mark.skipif(not (DEMO / "takeover_clone.wav").exists(), reason="demo clips not generated")


def settings():
    return Settings(llm_provider="stub", nebius_api_key="")


def copy_without_hints(tmp_path, name):
    """Copy WAV + transcript but NOT the .meta.json stub hints: fraud detector stands alone."""
    for ext in (".wav", ".txt"):
        shutil.copy(DEMO / f"{name}{ext}", tmp_path / f"{name}{ext}")
    return tmp_path / f"{name}.wav"


async def test_takeover_alerts_from_fraud_detector_alone(tmp_path):
    r = await analyze_wav(copy_without_hints(tmp_path, "takeover_clone"), settings())
    assert r.alert_level in ("caution", "high")
    assert "fraud" in r.fired
    assert r.signals["fraud"]["score"] >= 0.8
    assert r.trust < 70
    types = {e.type for e in r.events}
    assert {"transcript", "signal", "trust", "alert"} <= types
    assert sum(e.type == "transcript" for e in r.events) >= 4


async def test_takeover_with_stub_hints_goes_high():
    r = await analyze_wav(DEMO / "takeover_clone.wav", settings())
    assert r.alert_level == "high"
    assert set(r.fired) >= {"fraud", "spoof"}


async def test_benign_call_no_alert(tmp_path):
    r = await analyze_wav(copy_without_hints(tmp_path, "benign_balance"), settings())
    assert r.alert_level == "none"
    assert r.trust > 90


async def test_grandparent_is_caution():
    r = await analyze_wav(DEMO / "grandparent_vulnerable.wav", settings())
    assert r.alert_level == "caution"
    assert r.fired == ["fraud"]


async def test_no_sidecar_uses_placeholder_stt(tmp_path):
    shutil.copy(DEMO / "takeover_clone.wav", tmp_path / "x.wav")
    r = await analyze_wav(tmp_path / "x.wav", settings())
    assert "stub STT" in r.transcript
    assert r.alert_level == "none"


def test_websocket_replay_end_to_end(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module.settings, "replay_speed", 50.0)
    client = TestClient(app_module.app)
    assert client.get("/health").json()["status"] == "ok"
    assert any(c["name"] == "takeover_clone.wav" for c in client.get("/clips").json())
    events = []
    with client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "replay", "clip": "takeover_clone.wav"}))
        while True:
            ev = json.loads(ws.receive_text())
            events.append(ev)
            if ev["type"] == "status" and ev["state"] in ("replay_finished", "error"):
                break
        ws.send_text(json.dumps({"type": "replay", "clip": "../secrets.wav"}))
        err = json.loads(ws.receive_text())
        assert err["type"] == "status" and err["state"] == "error"
    types = {e["type"] for e in events}
    assert {"transcript", "signal", "trust", "alert"} <= types
    alerts = [e for e in events if e["type"] == "alert"]
    assert alerts[-1]["level"] == "high"
    assert alerts[-1]["suggested_action"]
