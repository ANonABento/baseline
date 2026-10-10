"""Transcript-level fraud eval harness (scripts/eval_fraud.py) + public-set fetcher parsing."""

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from detectors.fraud import FraudDetector

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses look up their module
    spec.loader.exec_module(mod)
    return mod


ev = _load("eval_fraud")
fetch = _load("fetch_text_eval")


def rec(label="scam", turns=None, **kw):
    turns = [{"speaker": "customer", "text": "hello"}] if turns is None else turns
    return {"id": kw.pop("id", "x"), "label": label, "scenario": kw.pop("scenario", "s"), "turns": turns, **kw}


# ---------------------------------------------------------------- parsing

@pytest.mark.parametrize("raw,want", [("scam", "scam"), ("FRAUD", "scam"), (1, "scam"), ("benign", "benign"), (0, "benign")])
def test_parse_record_label_aliases(raw, want):
    assert ev.parse_record(rec(label=raw))["label"] == want


@pytest.mark.parametrize("bad", [
    rec(label="maybe"),
    rec(turns=[]),
    rec(turns=[{"speaker": "customer"}]),
    rec(key_turn=5),
    "not a dict",
])
def test_parse_record_rejects_bad_input(bad):
    with pytest.raises(ev.DataError):
        ev.parse_record(bad, "t")


def test_parse_record_normalizes_speaker_and_defaults():
    r = ev.parse_record({"label": "benign", "turns": [{"speaker": " Customer ", "text": "hi"}]}, "f:1")
    assert r["turns"][0]["speaker"] == "customer"
    assert r["id"] == "f:1" and r["scenario"] == "unknown" and r["key_turn"] is None


def test_load_jsonl_skips_blank_and_reports_line(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text(json.dumps(rec()) + "\n\n" + json.dumps(rec(label="benign", id="y")) + "\n")
    assert [r["id"] for r in ev.load_jsonl(p)] == ["x", "y"]
    p.write_text(json.dumps(rec()) + "\n{oops\n")
    with pytest.raises(ev.DataError, match="d.jsonl:2"):
        ev.load_jsonl(p)


def test_caller_utterances_keeps_turn_index_as_id():
    r = rec(turns=[{"speaker": "agent", "text": "Hi, bank."}, {"speaker": "customer", "text": "Wire it."},
                   {"speaker": "customer", "text": "  "}, {"speaker": "customer", "text": "Now."}])
    assert ev.caller_utterances(r) == [(1, "Wire it."), (3, "Now.")]
    assert [u for u, _ in ev.caller_utterances(r, "all")] == [0, 1, 3]


def test_parse_bothbosu_dialogue():
    turns = fetch.parse_bothbosu_dialogue("caller: Hello, is this John? receiver: Yes. Caller: Your SSN is suspended.")
    assert turns == [
        {"speaker": "customer", "text": "Hello, is this John?"},
        {"speaker": "agent", "text": "Yes."},
        {"speaker": "customer", "text": "Your SSN is suspended."},
    ]


def test_stratified_sample_is_balanced_and_deterministic():
    rows = [{"label": i % 2, "type": f"t{i % 6}", "_idx": i} for i in range(120)]
    a = fetch.stratified_sample(rows, 40)
    assert len(a) == 40 and sum(r["label"] for r in a) == 20
    assert len({r["type"] for r in a if r["label"] == 1}) == 3  # odd ids -> t1, t3, t5
    assert [r["_idx"] for r in a] == [r["_idx"] for r in fetch.stratified_sample(rows, 40)]


def test_lakshan_record_filters_to_banking():
    conv = [{"speaker": "agent", "text": "Thanks for calling the bank."}, {"speaker": "client", "text": "Check my balance."}]
    r = fetch.lakshan_record({"conversation_id": "abc123", "conversation": conv})
    assert r["label"] == "benign" and r["turns"][1]["speaker"] == "customer"
    assert fetch.lakshan_record({"conversation_id": "z", "conversation": [
        {"speaker": "client", "text": "My pizza was cold."}]}) is None


# ---------------------------------------------------------------- metrics

def cr(label, alert_turn=None, n=4, score=0.0, scenario="s", key=None, alert_utt=None, ms=10.0):
    r = ev.CallResult(id=f"{label}{alert_turn}{score}", label=label, scenario=scenario, n_turns=n,
                      alert_turn=alert_turn, max_score=score, key_turn=key, alert_utt=alert_utt, call_ms=ms)
    r.max_level = "caution" if alert_turn else "none"
    r.strong = score >= ev.STRONG_SCORE
    r.engines = ["keywords"] * n
    return r


def test_compute_metrics_math():
    results = [
        cr("scam", alert_turn=1, n=4, score=0.9, key=5, alert_utt=3),   # alerted before key
        cr("scam", alert_turn=3, n=4, score=0.6, key=2, alert_utt=6),   # alerted after key
        cr("scam", n=4),                                                # miss
        cr("scam", alert_turn=2, n=2, score=0.7),                       # no key_turn
        cr("benign", alert_turn=2, n=4, score=0.85),                    # false alarm, strong
        cr("benign", n=4), cr("benign", n=4), cr("benign", n=4),
    ]
    m = ev.compute_metrics(results)
    assert (m["n"], m["n_scam"], m["n_benign"]) == (8, 4, 4)
    assert m["detection_rate"] == 0.75
    assert m["false_alarm_rate"] == 0.25
    assert m["precision"] == 0.75
    assert m["strong_scam_rate"] == 0.25 and m["strong_benign_rate"] == 0.25
    assert m["median_alert_turn"] == 2
    assert m["mean_alert_frac"] == round((0.25 + 0.75 + 1.0) / 3, 3)
    assert m["pre_key_rate"] == 0.5
    assert m["mean_call_ms"] == 10.0 and m["mean_turn_ms"] == round(80 / 30, 2)
    assert m["llm_fallback_rate"] is None  # keywords only


def test_compute_metrics_empty_classes_are_none():
    m = ev.compute_metrics([cr("benign", n=3)])
    assert m["detection_rate"] is None and m["precision"] is None and m["median_alert_turn"] is None
    assert m["false_alarm_rate"] == 0.0


def test_llm_fallback_rate():
    r = cr("benign")
    r.engines = ["llm", "llm", "llm", "keywords"]
    assert ev.compute_metrics([r])["llm_fallback_rate"] == 0.25


def test_per_scenario():
    sc = ev.per_scenario([cr("scam", 1, scenario="a"), cr("scam", scenario="a"), cr("benign", scenario="b")])
    assert sc == {("benign", "b"): (0, 1), ("scam", "a"): (1, 2)}


def test_history_append_writes_header_once(tmp_path):
    p = tmp_path / "h.csv"
    m = ev.compute_metrics([cr("scam", 1), cr("benign")])
    row = ev.history_row("held_out", m, "keywords", None, "customer", "note", "abc", "ts")
    ev.append_history([row], p)
    ev.append_history([row], p)
    rows = list(csv.DictReader(p.open()))
    assert len(rows) == 2 and rows[0]["dataset"] == "held_out" and rows[0]["detection_rate"] == "1.0"
    assert list(rows[0]) == ev.HISTORY_FIELDS


# ---------------------------------------------------------------- replay through the real detector

async def test_replay_call_time_to_alert_keywords():
    r = ev.parse_record({
        "id": "t", "label": "scam", "scenario": "grandparent", "key_turn": 3,
        "turns": [
            {"speaker": "agent", "text": "Hello, how can I help?"},
            {"speaker": "customer", "text": "I need to take out some money."},
            {"speaker": "customer", "text": "My grandson was arrested and needs bail."},
            {"speaker": "customer", "text": "A courier will pick up the cash."},
        ],
    })
    res = await ev.replay_call(FraudDetector(None), r)
    assert res.n_turns == 3 and res.alerted
    assert res.alert_turn == 2 and res.alert_utt == 2 and res.pre_key is True
    assert res.trigger["id"] == "grandparent_bail" and res.trigger["utterance_id"] == 2
    assert set(res.engines) == {"keywords"}


async def test_replay_call_benign_stays_quiet():
    r = ev.parse_record(rec(label="benign", turns=[
        {"speaker": "customer", "text": "Hi, I'd like to check my balance."},
        {"speaker": "customer", "text": "Thanks, that's all."}]))
    res = await ev.replay_call(FraudDetector(None), r)
    assert not res.alerted and res.alert_turn is None and res.max_level == "none"


# ---------------------------------------------------------------- the held-out set itself

def test_held_out_set_is_well_formed():
    recs = ev.load_jsonl(ev.DATASETS["held_out"])
    by_id = {r["id"]: r for r in recs}
    assert len(by_id) == len(recs) >= 40
    scams = [r for r in recs if r["label"] == "scam"]
    assert len(scams) * 2 == len(recs)
    for s in scams:
        twin = by_id[s["twin_of"]]
        assert twin["label"] == "benign" and twin["twin_of"] == s["id"]
        assert s["key_turn"] is not None and s["turns"][s["key_turn"]]["speaker"] == "customer"
    for r in recs:
        assert 5 <= len(r["turns"]) <= 12, r["id"]
    raw = [json.loads(line) for line in ev.DATASETS["held_out"].read_text().splitlines() if line.strip()]
    assert all(x.get("held_out") is True for x in raw)
