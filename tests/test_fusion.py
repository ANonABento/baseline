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


# ---------------------------------------------------------------- helpers for evidence-shaped results

def pat(pid, name, severity, quote, uid, action=""):
    return {"id": pid, "name": name, "severity": severity, "quote": quote, "utterance_id": uid,
            "source": f"https://kb/{pid}", "suggested_agent_action": action or f"Action for {pid}."}


def fraud(score, patterns, conf=0.8, reason="fraud reason", action="analyzer action"):
    return r("fraud", score, conf=conf, reason=reason, patterns=patterns, engine="keywords", model=None,
             citations=[{"pattern_id": p["id"], "name": p["name"], "source": p["source"]} for p in patterns],
             suggested_action=action)


ATO = pat("account_takeover", "Account takeover", "high", "change the phone number on my account", 3,
          "Do not change contact details; call back on the number on file.")
EVASION = pat("verification_evasion", "Verification evasion", "medium", "I don't have time for questions", 2)
GRANDPARENT = pat("grandparent_scam", "Grandparent scam", "high", "my grandson is in jail and needs bail money", 4,
                  "Gently ask who asked for the money; offer to pause the transfer.")


# ---------------------------------------------------------------- alert dedupe (material changes only)

def test_rewording_and_jitter_do_not_reemit():
    f = Fusion()
    f.alert_if_changed()
    f.update(fraud(0.85, [ATO], reason="first wording"))
    assert f.alert_if_changed().level == "caution"
    for i, s in enumerate([0.9, 0.82, 0.95, 0.88]):
        f.update(fraud(s, [ATO], reason=f"wording {i}"))
        assert f.alert_if_changed() is None


def test_signal_dropping_below_threshold_and_back_does_not_reemit():
    f = Fusion()
    f.alert_if_changed()
    f.update(fraud(0.9, [ATO]))
    f.update(r("spoof", 0.95, conf=0.7, p_fake_max=0.97))
    assert f.alert_if_changed().level == "high"
    for s in (0.1, 0.1, 0.95, 0.1, 0.95):  # spoof EMA flaps across the threshold
        f.update(r("spoof", s, conf=0.7))
        assert f.alert_if_changed() is None


def test_new_pattern_at_same_level_reemits():
    f = Fusion()
    f.alert_if_changed()
    f.update(fraud(0.85, [EVASION]))
    assert f.alert_if_changed().level == "caution"
    f.update(fraud(0.9, [EVASION, ATO]))
    a = f.alert_if_changed()
    assert a is not None and a.level == "caution"
    assert {c.pattern_id for c in a.citations} == {"verification_evasion", "account_takeover"}
    f.update(fraud(0.9, [ATO]))  # pattern scrolled out of the analyzer window: nothing new
    assert f.alert_if_changed() is None


def test_new_signal_at_same_level_reemits():
    f = Fusion()
    f.alert_if_changed()
    f.update(fraud(0.9, [ATO]))
    f.update(r("spoof", 0.9, conf=0.7))
    assert f.alert_if_changed().level == "high"
    f.update(r("speaker", 0.9, conf=0.8, similarity=0.2))
    a = f.alert_if_changed()
    assert a is not None and a.level == "high" and "speaker" in a.signals
    assert f.alert_if_changed() is None


def test_level_change_reemits():
    f = Fusion()
    assert f.alert_if_changed().level == "none"
    f.update(fraud(0.9, [ATO]))
    assert f.alert_if_changed().level == "caution"
    f.update(r("spoof", 0.9, conf=0.7))
    assert f.alert_if_changed().level == "high"


def test_evidence_latches_after_signal_decays():
    f = Fusion()
    f.update(fraud(0.9, [ATO]))
    f.update(fraud(0.1, []))  # analyzer later sees a calmer window
    a = f.alert_event()
    assert a.level == "caution" and a.signals == ["fraud"]
    assert any("Account takeover" in x for x in a.reasons)


# ---------------------------------------------------------------- evidence in the alert

def test_fraud_reason_has_top_quote_and_action_from_highest_severity():
    f = Fusion()
    f.update(fraud(0.9, [EVASION, ATO], action="analyzer action"))
    a = f.alert_event()
    assert a.reasons[0] == ('Fraud pattern "Account takeover": "change the phone number on my account" '
                            "(utterance 3)")
    assert "Verification evasion" in a.reasons[1]
    assert a.suggested_action == ATO["suggested_agent_action"]
    assert {c.pattern_id for c in a.citations} == {"account_takeover", "verification_evasion"}


def test_fraud_without_patterns_falls_back_to_details_action():
    f = Fusion()
    f.update(r("fraud", 0.9, reason="LLM says scam", suggested_action="Call back on file.", citations=[]))
    a = f.alert_event()
    assert a.suggested_action == "Call back on file."
    assert a.reasons == ["Fraud analyzer: LLM says scam"]


def test_speaker_and_spoof_reasons_state_numbers():
    f = Fusion()
    f.update(r("speaker", 0.92, conf=0.8, similarity=0.22, accept_sim=0.55, reject_sim=0.30))
    f.update(r("spoof", 0.93, conf=0.7, p_fake_max=0.97))
    a = f.alert_event()
    assert a.level == "high"
    assert "Voice doesn't match enrolled customer (similarity 0.22)" in a.reasons
    assert "Synthetic voice likely (P=0.93)" in a.reasons
    assert a.suggested_action.startswith("Do not process")


def test_speaker_reason_without_similarity_uses_risk():
    f = Fusion()
    f.update(r("speaker", 0.85, conf=0.8, stub=True))
    assert f.alert_event().reasons == ["Voice doesn't match enrolled customer (risk 0.85)"]


# ---------------------------------------------------------------- demo scenarios

def test_scenario_account_takeover_clone_is_high():
    """Cloned voice passes voice-ID, but spoof + fraud fire -> high."""
    f = Fusion()
    f.alert_if_changed()
    emitted = []
    script = [
        [r("speaker", 0.08, conf=0.8, similarity=0.71), r("spoof", 0.86, conf=0.7), fraud(0.2, [])],
        [r("speaker", 0.1, conf=0.8, similarity=0.68), r("spoof", 0.91, conf=0.7), fraud(0.6, [EVASION])],
        [r("speaker", 0.07, conf=0.8, similarity=0.73), r("spoof", 0.88, conf=0.7), fraud(0.92, [EVASION, ATO])],
        [r("speaker", 0.09, conf=0.8, similarity=0.70), r("spoof", 0.9, conf=0.7), fraud(0.93, [EVASION, ATO])],
    ]
    for utt in script:
        for res in utt:
            f.update(res)
        f.trust_event(0)
        ev = f.alert_if_changed()
        if ev:
            emitted.append(ev)
    final = f.alert_event()
    assert final.level == "high"
    assert "speaker" not in final.signals and set(final.signals) == {"fraud", "spoof"}
    assert final.reasons[0].startswith('Fraud pattern "Account takeover"')
    assert any(x.startswith("Synthetic voice likely (P=") for x in final.reasons)
    assert any(x.startswith("Voice matches enrolled customer (similarity") for x in final.reasons)
    assert ATO["suggested_agent_action"] in final.suggested_action
    assert final.suggested_action.startswith("Do not process")
    assert len(emitted) <= 4 and emitted[-1].level == "high"
    assert f.alert_if_changed() is None


def test_scenario_vulnerable_customer_is_caution_with_fraud_action():
    """Genuine customer voice, real human, grandparent script -> caution, never high."""
    f = Fusion()
    for score in (0.3, 0.7, 0.95, 0.97):
        f.update(r("speaker", 0.05, conf=0.8, similarity=0.8))
        f.update(r("spoof", 0.05, conf=0.7))
        f.update(fraud(score, [GRANDPARENT] if score >= 0.7 else []))
        f.trust_event(0)
    a = f.alert_event()
    assert a.level == "caution"
    assert a.signals == ["fraud"]
    assert a.suggested_action == GRANDPARENT["suggested_agent_action"]
    assert "my grandson is in jail" in a.reasons[0]


def test_single_high_severity_fraud_is_caution_not_high():
    f = Fusion()
    f.update(fraud(1.0, [ATO, GRANDPARENT], conf=1.0))
    assert f.alert_event().level == "caution"


def test_scenario_benign_call_is_none():
    f = Fusion()
    f.alert_if_changed()
    for _ in range(5):
        f.update(r("speaker", 0.06, conf=0.8, similarity=0.75))
        f.update(r("spoof", 0.08, conf=0.7))
        f.update(fraud(0.05, []))
        f.trust_event(0)
        assert f.alert_if_changed() is None
    a = f.alert_event()
    assert a.level == "none" and a.reasons == [] and a.signals == []
    assert f.trust > 85


def test_scenario_benign_call_with_low_confidence_spoof_blip_is_none():
    f = Fusion()
    f.alert_if_changed()
    for i in range(6):
        f.update(r("speaker", 0.06, conf=0.8, similarity=0.75))
        # one short noisy utterance: spoof says 0.75 but with low confidence
        f.update(r("spoof", 0.75, conf=0.35) if i == 3 else r("spoof", 0.08, conf=0.7))
        f.update(fraud(0.05, []))
        f.trust_event(0)
        assert f.alert_if_changed() is None
    assert f.alert_event().level == "none"


def test_min_evidence_blocks_low_product_even_above_individual_thresholds():
    from fusion import MIN_EVIDENCE

    f = Fusion()
    f.update(r("spoof", 0.6, conf=0.4))  # 0.6 >= 0.5, 0.4 >= 0.3, but 0.24 < MIN_EVIDENCE
    assert 0.6 * 0.4 < MIN_EVIDENCE
    assert f.fired() == [] and f.compute_level() == "none"
