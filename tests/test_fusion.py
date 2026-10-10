from events import DetectorResult
from fusion import Fusion


def r(signal, score, conf=0.8, reason="x", **details):
    return DetectorResult(signal=signal, score=score, confidence=conf, reason=reason, details=details)


def test_no_signals_full_trust_and_no_alert():
    f = Fusion()
    t = f.trust_event(0)
    assert t.score == 100.0 and t.raw == 100.0
    a = f.alert_event()
    assert a.level == "none" and a.signals == [] and a.suggested_action == ""


def test_zero_confidence_stub_is_ignored():
    f = Fusion()
    f.update(r("spoof", 1.0, conf=0.0))
    assert f.raw_trust() == 100.0
    assert f.compute_level() == "none"


def test_single_signal_is_caution():
    f = Fusion()
    f.update(r("fraud", 0.9, suggested_action="Call back on file.",
               citations=[{"pattern_id": "gift_cards", "name": "Gift cards", "source": "https://x"}]))
    a = f.alert_event()
    assert a.level == "caution"
    assert a.signals == ["fraud"]
    assert a.suggested_action == "Call back on file."
    assert a.citations[0].pattern_id == "gift_cards"


def test_two_independent_hard_signals_is_high():
    f = Fusion()
    f.update(r("fraud", 0.9))
    f.update(r("spoof", 0.9))
    a = f.alert_event()
    assert a.level == "high"
    assert set(a.signals) == {"fraud", "spoof"}
    assert "Do not process" in a.suggested_action


def test_prosody_alone_never_high():
    f = Fusion()
    f.update(r("prosody", 1.0, conf=0.9))
    f.update(r("fraud", 0.9))
    assert f.compute_level() == "caution"  # prosody is soft, only 1 hard signal


def test_below_threshold_does_not_fire():
    f = Fusion()
    f.update(r("fraud", 0.4))
    assert f.compute_level() == "none"
    assert f.raw_trust() < 100.0  # but still lowers trust


def test_trust_drops_fast_recovers_slow_and_level_latches():
    f = Fusion()
    f.update(r("fraud", 0.95, conf=0.9))
    f.update(r("spoof", 0.95, conf=0.9))
    low = f.trust_event(0).score
    assert low < 40
    assert f.alert_event().level == "high"
    f.update(r("fraud", 0.0, conf=0.9))
    for _ in range(3):
        f.update(r("spoof", 0.0, conf=0.9))
    t1 = f.trust_event(1).score
    assert low < t1 < 100  # recovering, but smoothed
    assert f.alert_event().level == "high"  # latched for the call
    f.reset()
    assert f.alert_event().level == "none" and f.trust == 100.0


def test_noisy_or_accumulates():
    f = Fusion()
    f.update(r("fraud", 0.6))
    one = f.raw_trust()
    f.update(r("speaker", 0.6))
    assert f.raw_trust() < one


def test_alert_if_changed_dedupes():
    f = Fusion()
    assert f.alert_if_changed() is not None  # initial "none"
    assert f.alert_if_changed() is None
    f.update(r("fraud", 0.9))
    assert f.alert_if_changed().level == "caution"
    assert f.alert_if_changed() is None
