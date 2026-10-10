"""session_signals known-answer tests + credential issue/verify/tamper (software correctness only)."""

import copy
import sys
from pathlib import Path

import pytest

from detectors.session_signals import analyse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def report():
    tr = [  # interviewer (analyzed False) speaks, candidate (analyzed True) answers
        {"utterance_id": 0, "speaker": "ai", "analyzed": False, "text": "Why did you approve it?", "t_start": 0.0, "t_end": 3.0},
        {"utterance_id": 1, "speaker": "visitor", "analyzed": True, "text": "Um I checked the policy first", "t_start": 4.0, "t_end": 7.0},
        {"utterance_id": 2, "speaker": "ai", "analyzed": False, "text": "Do it now or lose the account!", "t_start": 7.5, "t_end": 10.0},
        {"utterance_id": 3, "speaker": "visitor", "analyzed": True, "text": "I will not do that without verification", "t_start": 12.0, "t_end": 16.0},
        {"utterance_id": 4, "speaker": "visitor", "analyzed": True, "text": "Let us slow down and check each step", "t_start": 20.0, "t_end": 24.0},
        {"utterance_id": 5, "speaker": "visitor", "analyzed": True, "text": "Thank you for waiting", "t_start": 30.0, "t_end": 33.0},
    ]
    def sig(u, z_f0, z_rms, change, status="ok"):
        return {"signal": "prosody", "utterance_id": u, "details": {"status": status, "delivery_change": change,
                "z": {"f0_median_st": z_f0, "rms_db": z_rms, "f0_std_st": 0.0, "rate_proxy": 0.0, "pause_frac": 0.0},
                "features": {"pause_frac": 0.2}}}
    return {"id": "sess0001", "transcript": tr, "signals": [sig(1, 0.1, 0.0, 0.0), sig(3, 3.5, 2.0, 0.6), sig(4, 1.0, 0.5, 0.0), sig(5, 0.2, 0.1, 0.0)]}


def test_known_answers():
    o = analyse(report())
    assert o["n_turns_analysed"] == 4 and o["calibration_status"] == "not_established"
    # turn 1 starts 4.0 after the interviewer ended 3.0 (1.0 s); turn 3 starts 12.0 after 10.0 (2.0 s); turns 4 and 5 follow the candidate, so they do not count
    assert o["response_latency_s"] == {"mean": 1.5, "max": 2.0, "n": 2}
    assert o["hesitation"]["fillers_per_100_words"] > 0  # "Um"
    assert o["recovery_latency"] == {"peak_at_s": 16.0, "latency_s": 4.0, "status": "recovered"}  # next in-range turn starts at 20.0
    assert o["tone_drift"]["max_abs_z"] == 3.5


def test_no_peak_and_not_recovered():
    r = report()
    for s in r["signals"]:
        s["details"]["z"] = {k: 0.1 for k in s["details"]["z"]}
    assert analyse(r)["recovery_latency"] == {"status": "no_peak_over_threshold"}
    r2 = report()
    r2["signals"] = r2["signals"][:2]
    assert analyse(r2)["recovery_latency"]["status"] == "not_recovered_in_call"


def test_credential_roundtrip_and_tamper(tmp_path):
    pytest.importorskip("cryptography")
    import credential as c

    cred = c.issue(report(), [{"t": 12.0, "decision": "refused to act without verification"}], tmp_path / "k.key")
    assert c.verify(cred, report())[0]
    assert c.verify(cred)[1] == "signature valid (report not checked)"
    bad = copy.deepcopy(cred)
    bad["payload"]["signals"]["recovery_latency"]["latency_s"] = 0.1
    assert not c.verify(bad)[0]
    other = report()
    other["transcript"][1]["text"] = "changed"
    assert c.verify(cred, other) == (False, "signature valid, but the report does not match report_sha256")
    assert c.public_from_did(cred["payload"]["issuer"]) and cred["payload"]["issuer"].startswith("did:key:z6Mk")
