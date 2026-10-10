"""voice_state: known-answer z-score step + synthetic-audio behaviour. Software tests only:
they show the code does what it says, not that the signal means stress (calibration not established)."""

import asyncio

import numpy as np
import pytest

from core import CallContext, Utterance
from detectors import voice_state as vs
from detectors.prosody import ProsodyDetector

SR = 16_000


def voiced(f0: float, seconds: float = 2.0, amp: float = 0.2, seed: int = 0) -> np.ndarray:
    """Harmonic 'syllables' (4 per second) with a little noise, at fundamental f0."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    carrier = sum(np.sin(2 * np.pi * f0 * h * t) / h for h in range(1, 6))
    env = 0.5 * (1 + np.sin(2 * np.pi * 4 * t - np.pi / 2)) ** 0.5
    return (amp * carrier * env / 2 + 0.0005 * rng.standard_normal(t.size)).astype(np.float32)


def feats(f0: float, **kw):
    return vs.extract_features(voiced(f0, **kw), SR)


def test_zscore_known_answer():
    base = vs.SpeakerBaseline(min_n=3)
    for v in (10.0, 12.0, 14.0):  # median 12, MAD 2 -> spread 2.9652 (above the 2 dB floor)
        row = dict.fromkeys(vs.FEATURES, 0.0)
        row["rms_db"] = v
        base.rows.append(row)
    f = dict.fromkeys(vs.FEATURES, 0.0)
    f["rms_db"] = 12.0 + 2 * 2.9652
    z = base.zscores(f)
    assert z["rms_db"] == pytest.approx(2.0, abs=1e-9)
    assert z["f0_median_st"] == 0.0  # zero spread -> floor, zero difference -> z 0


def test_pitch_extraction_close_to_truth():
    f = feats(150.0)
    assert f is not None
    assert 12 * np.log2(150.0) == pytest.approx(f["f0_median_st"], abs=1.0)


def test_short_clip_is_insufficient():
    f = vs.extract_features(voiced(150.0, seconds=0.5), SR)
    assert "under 1 s of speech" in vs.quality_problems(f)


def test_clipped_and_noise_rejected():
    clipped = np.clip(voiced(150.0) * 20, -1, 1)
    assert "clipped audio" in vs.quality_problems(vs.extract_features(clipped, SR))
    noise = (0.1 * np.random.default_rng(1).standard_normal(2 * SR)).astype(np.float32)
    assert vs.quality_problems(vs.extract_features(noise, SR))  # something is wrong with it


def test_baseline_then_stable_then_sustained_shift():
    base = vs.SpeakerBaseline(min_n=3)
    for s in range(3):
        d = vs.assess(feats(150.0, seed=s), base)
        assert d["status"] == "building_baseline" and d["stress_related_change"] is None
    d = vs.assess(feats(150.0, seed=9), base)
    assert d["status"] == "ok" and d["stress_related_change"] == 0.0 and d["delivery_markers"] == []
    for seed in (10, 11):  # shifted utterances before the sustain count is reached: not reported
        assert vs.assess(feats(230.0 + seed, seed=seed, amp=0.4), base)["stress_related_change"] == 0.0
    d2 = vs.assess(feats(241.0, seed=12, amp=0.4), base)  # third in a row: reported
    assert d2["stress_related_change"] > 0.0
    assert any("pitch" in m for m in d2["delivery_markers"])
    assert d2["calibration_status"] == "not_established"
    assert not any("lie" in k or "decept" in k or "honest" in k for k in d2)


def test_poor_audio_resets_streak_and_never_joins_baseline():
    base = vs.SpeakerBaseline(min_n=3)
    for s in range(3):
        vs.assess(feats(150.0, seed=s), base)
    vs.assess(feats(230.0, seed=10, amp=0.4), base)
    assert base.streak == 1
    d = vs.assess(vs.extract_features(voiced(150.0, seconds=0.4), SR), base)
    assert d["status"] == "insufficient_evidence" and base.streak == 0 and len(base.rows) == 3


def test_detector_contract_and_fusion_confidence():
    det, ctx = ProsodyDetector(), CallContext()

    def run(audio, i):
        return asyncio.run(det.analyze(Utterance(id=i, audio=audio, sample_rate=SR, t_start=i * 3.0, t_end=i * 3.0 + 2), ctx))

    out = [run(voiced(150.0, seed=i), i) for i in range(3)]
    assert all(r.confidence == 0.0 and r.signal == "prosody" for r in out)  # fusion ignores while building
    r = run(voiced(150.0, seed=7), 3)
    assert r.confidence == 0.25 and r.score == 0.0 and r.details["status"] == "ok"
    r = run(voiced(150.0, seconds=0.3), 4)
    assert r.confidence == 0.0 and r.details["status"] == "insufficient_evidence"


@pytest.mark.parametrize("bad", [np.zeros(0, np.float32), np.full(SR * 2, np.nan, np.float32), np.full(SR * 2, np.inf, np.float32), np.zeros(SR * 2, np.float32)])
def test_bad_audio_never_raises(bad):
    f = vs.extract_features(bad, SR)
    assert vs.quality_problems(f)  # None or flagged (silence has no voiced speech)
    d = vs.assess(f, vs.SpeakerBaseline())
    assert d["status"] == "insufficient_evidence"
