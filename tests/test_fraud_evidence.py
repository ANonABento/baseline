"""Evidence contract, quote validation, new patterns and false-positive control."""

import json
from pathlib import Path

import numpy as np
import pytest

from core import CallContext, Utterance
from detectors.fraud import FraudDetector, build_user_prompt
from detectors.fraud_rules import (
    MAX_QUOTE_CHARS,
    NO_EVIDENCE_SCORE_CAP,
    find_quote,
    keyword_assess,
    match_patterns,
    normalize,
    normalize_with_map,
    playbook_by_id,
    validate_llm_patterns,
)
from providers.base import LLMProvider
from providers.llm_stub import StubLLM, parse_numbered_transcript

DEMO = Path(__file__).resolve().parent.parent / "data" / "demo"
PATTERN_KEYS = {"id", "name", "severity", "quote", "utterance_id", "source", "suggested_agent_action"}
OPTIONAL_PATTERN_KEYS = {"say_this"}  # calm line the agent can say verbatim (kb say_this)


def demo_utts(name):
    lines = [l for l in (DEMO / name).read_text().splitlines() if l.strip() and not l.startswith("#")]
    return [(i, l.split("] ", 1)[1] if l.startswith("[") else l) for i, l in enumerate(lines)]


def ctx_from(utts):
    ctx = CallContext()
    for uid, text in utts:
        ctx.utterances.append(Utterance(id=uid, audio=np.zeros(160, np.float32), sample_rate=16000,
                                        t_start=float(uid), t_end=uid + 0.9, text=text))
    return ctx


def assert_contract(details, utts):
    assert set(details) >= {"patterns", "engine", "model", "citations", "suggested_action"}
    assert details["engine"] in ("llm", "keywords")
    texts = dict(utts)
    pb = playbook_by_id()
    for p in details["patterns"]:
        assert PATTERN_KEYS <= set(p) <= PATTERN_KEYS | OPTIONAL_PATTERN_KEYS
        assert isinstance(p["id"], str) and p["id"] in pb
        assert p["name"] == pb[p["id"]].name
        assert p["severity"] in ("low", "medium", "high")
        assert isinstance(p["utterance_id"], int) and p["utterance_id"] in texts
        assert isinstance(p["quote"], str) and 0 < len(p["quote"]) <= MAX_QUOTE_CHARS
        assert p["quote"] in texts[p["utterance_id"]], (p["quote"], texts[p["utterance_id"]])
        assert p["source"].startswith("https://")
        assert p["suggested_agent_action"]
    # JSON-serializable (it goes over the WebSocket)
    json.dumps(details)


class FakeLLM(LLMProvider):
    """Returns a canned completion; records the prompt."""

    name = "fake"
    model = "fake/model-1"

    def __init__(self, payload):
        self.payload = payload
        self.user = None

    async def complete(self, system, user, *, json_mode=True):
        self.user = user
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload)


# ---------------------------------------------------------------- normalization map

@pytest.mark.parametrize(
    "text",
    ["Don’t TELL anyone!!", "$9,000.", "I'd like a, b,1 — x  ", "  ¿Qué?  wire  $5,000, now. ", "İstanbul", "", "...", "a,,1"],
)
def test_normalize_with_map_matches_normalize(text):
    n, m = normalize_with_map(text)
    assert n == normalize(text)
    assert len(m) == len(n)
    assert all(0 <= i < len(text) for i in m)


# ---------------------------------------------------------------- evidence shape (keywords / stub)

@pytest.mark.parametrize("clip", ["takeover_clone.txt", "grandparent_vulnerable.txt", "benign_balance.txt"])
@pytest.mark.parametrize("llm", [None, StubLLM()])
async def test_evidence_contract_on_demo_clips(clip, llm):
    utts = demo_utts(clip)
    r = await FraudDetector(llm).analyze(None, ctx_from(utts))
    assert_contract(r.details, utts)
    assert r.details["engine"] == "keywords" and r.details["model"] is None
    if clip.startswith("benign"):
        assert r.score < 0.5 and r.details["patterns"] == []
    else:
        assert r.score >= 0.8
        top = r.details["patterns"][0]
        assert top["name"] in r.reason and top["severity"] == "high"
        assert r.details["citations"][0]["pattern_id"] == top["id"]
        assert r.details["suggested_action"] == top["suggested_agent_action"]


async def test_takeover_quotes_the_wire_line():
    utts = demo_utts("takeover_clone.txt")
    r = await FraudDetector(None).analyze(None, ctx_from(utts))
    ato = next(p for p in r.details["patterns"] if p["id"] == "ato_contact_change_then_money")
    assert ato["utterance_id"] == 2 and "wire nine thousand dollars" in ato["quote"]


async def test_utterance_ids_are_real_ids_not_positions():
    utts = [(41, "Hi, I need to update my email address."), (47, "Then wire 9,000 dollars to a new account right now.")]
    r = await FraudDetector(None).analyze(None, ctx_from(utts))
    assert_contract(r.details, utts)
    assert {p["utterance_id"] for p in r.details["patterns"]} <= {41, 47}


def test_long_utterance_quote_is_capped_and_verbatim():
    filler = "and then I went to the store and talked to my neighbor about the weather for a while "
    text = filler * 4 + "he told me not to tell anyone about it " + filler * 4
    a = keyword_assess([(3, text)])
    e = next(e for e in a.evidence if e.id == "secrecy")
    assert len(e.quote) <= MAX_QUOTE_CHARS and e.quote in text and "not to tell anyone" in e.quote


def test_numbered_transcript_roundtrip():
    prompt = build_user_prompt([(5, "hello there"), (9, "wire it\nnow")])
    assert "[u5] hello there" in prompt and "[u9] wire it now" in prompt
    block = prompt.split("<transcript>")[1].split("</transcript>")[0]
    assert parse_numbered_transcript(block) == [(5, "hello there"), (9, "wire it now")]


def test_prompt_is_compact_and_lists_every_pattern():
    prompt = build_user_prompt([(0, "hi")])
    for pid in playbook_by_id():
        assert f"- {pid}:" in prompt
    assert "verification_evasion" in prompt and "coached_customer" in prompt
    assert len(prompt) < 4500  # ~1k tokens: keeps time-to-first-token low


# ---------------------------------------------------------------- LLM quote validation

UTTS = [
    (10, "Hi, this is Margaret, calling about my account."),
    (11, "My grandson was arrested and he needs bail money right away."),
    (12, "He told me not to tell anyone, he's so embarrassed."),
]


def test_quote_found_with_wrong_utterance_id_is_remapped():
    ev = validate_llm_patterns([{"id": "secrecy", "u": 11, "quote": "told me not to tell anyone"}], UTTS)
    assert ev[0].utterance_id == 12 and ev[0].quote == "told me not to tell anyone"


def test_quote_case_and_punctuation_are_repaired_to_verbatim():
    ev = validate_llm_patterns([{"id": "grandparent_bail", "u": "u11", "quote": "\"my GRANDSON was arrested, and he needs bail money\""}], UTTS)
    assert ev[0].utterance_id == 11
    assert ev[0].quote == "My grandson was arrested and he needs bail money"


def test_unknown_ids_and_garbage_items_are_dropped():
    items = [{"id": "made_up", "u": 11, "quote": "arrested"}, 42, None, {"u": 11}, "also_made_up"]
    assert validate_llm_patterns(items, UTTS) == []


def test_fabricated_quote_falls_back_to_keyword_quote_for_that_pattern():
    ev = validate_llm_patterns([{"id": "grandparent_bail", "u": 11, "quote": "please send bail to my grandson in Mexico"}], UTTS)
    assert ev and ev[0].utterance_id == 11 and ev[0].quote in UTTS[1][1]


def test_fabricated_quote_without_keyword_support_is_dropped():
    ev = validate_llm_patterns([{"id": "gift_cards", "u": 12, "quote": "pay with Google Play gift cards"}], UTTS)
    assert ev == []


def test_paraphrased_quote_repaired_by_word_overlap():
    utts = [(1, "Honestly I cannot answer that one right now. Can we just hurry this along.")]
    ev = validate_llm_patterns([{"id": "verification_evasion", "u": 1, "quote": "I cannot answer that right now"}], utts)
    assert ev and ev[0].quote == "Honestly I cannot answer that one right now."


def test_ellipsis_quote_uses_longest_fragment():
    hit = find_quote("my grandson... needs bail money right away", UTTS)
    assert hit == (11, "needs bail money right away")


def test_quote_must_match_on_word_boundaries():
    assert find_quote("ire nine", [(0, "I need to wire nine thousand")]) is None


async def test_llm_path_produces_contract_with_model():
    llm = FakeLLM({"risk": 0.92, "confidence": 0.8, "reason": "x",
                   "patterns": [{"id": "secrecy", "u": 12, "quote": "He told me not to tell anyone"},
                                {"id": "grandparent_bail", "u": 11, "quote": "grandson was arrested"},
                                {"id": "nonexistent", "u": 11, "quote": "arrested"}]})
    r = await FraudDetector(llm).analyze(None, ctx_from(UTTS))
    assert_contract(r.details, UTTS)
    assert r.details["engine"] == "llm" and r.details["model"] == "fake/model-1"
    assert [p["id"] for p in r.details["patterns"]] == ["grandparent_bail", "secrecy"]  # severity order
    assert r.score == pytest.approx(0.92)
    assert "Grandparent" in r.reason
    assert "[u11] My grandson" in llm.user


async def test_llm_high_risk_without_valid_evidence_is_capped():
    llm = FakeLLM({"risk": 0.95, "patterns": [{"id": "gift_cards", "u": 10, "quote": "buy gift cards now"}]})
    r = await FraudDetector(llm).analyze(None, ctx_from(UTTS))
    assert r.details["engine"] == "llm"
    assert r.details["patterns"] == []
    assert r.score <= NO_EVIDENCE_SCORE_CAP


async def test_llm_window_limits_context():
    utts = [(i, f"line number {i}") for i in range(30)]
    llm = FakeLLM({"risk": 0.0, "patterns": []})
    await FraudDetector(llm, max_utterances=5).assess(utts)
    assert "[u25]" in llm.user and "[u24]" not in llm.user


async def test_think_block_and_fences_are_tolerated():
    raw = '<think>maybe {"risk": 1}</think>\n```json\n{"risk": 0.7, "patterns": [{"id": "secrecy", "u": 12, "quote": "not to tell anyone"}]}\n```'
    a = await FraudDetector(FakeLLM(raw)).assess(UTTS)
    assert a.method == "llm" and a.score == pytest.approx(0.7) and a.pattern_ids == ["secrecy"]


# ---------------------------------------------------------------- new patterns

@pytest.mark.parametrize(
    "text",
    [
        "I don't have that on me, can we just do it quickly?",
        "Can we skip the security questions? I don't have time for this.",
        "Why do you need to know that? Just process it.",
        "I don't remember my PIN, can we just do this quickly.",
    ],
)
def test_verification_evasion_detected(text):
    assert "verification_evasion" in {m.pattern.id for m in match_patterns(text)}


def test_verification_evasion_plus_urgency_fires():
    a = keyword_assess([(1, "I don't have that on me, can we just do it quickly? It's urgent, I need it right now.")])
    assert a.score >= 0.5
    assert a.evidence[0].id == "verification_evasion"


@pytest.mark.parametrize(
    "text",
    [
        "He says I need to move all of it today.",
        "They told me not to tell you why.",
        "The man on the other line said this is the only way.",
        "Hold on, let me ask him what the account number is.",
        "I'm supposed to say it's for a family member.",
    ],
)
def test_coached_customer_detected(text):
    hits = {m.pattern.id for m in match_patterns(text)}
    assert "coached_customer" in hits
    a = keyword_assess([(0, text)])
    e = next(e for e in a.evidence if e.id == "coached_customer")
    assert e.severity == "high" and e.quote in text


def test_new_patterns_have_sources_and_actions():
    pb = playbook_by_id()
    for pid in ("verification_evasion", "coached_customer"):
        assert pb[pid].source_url.startswith("https://")
        assert pb[pid].suggested_agent_action
    assert "coached_caller" not in pb


# ---------------------------------------------------------------- false positives

BENIGN = [
    "I'd like to dispute a wire I didn't recognize on my statement.",
    "I bought a gift card for my niece, is that charge normal?",
    "I forgot my password for online banking, can you help me reset it?",
    "I don't remember my password, can I reset it online?",
    "Can you help me set up a wire transfer for my mortgage closing next week?",
    "Someone called saying they were from the bank and I hung up. I wanted to report it.",
    "Is there a fee if I wire money internationally?",
    "My card was declined at the store, can you check if there's a hold?",
    "I want to buy a gift card for my nephew's birthday, do you sell them at the branch?",
]


@pytest.mark.parametrize("text", BENIGN)
def test_benign_mentions_do_not_fire_keywords(text):
    a = keyword_assess([(0, text)])
    assert a.score < 0.5, (text, a.reason)
    assert all(e.severity != "high" for e in a.evidence), a.evidence


@pytest.mark.parametrize("text", BENIGN)
async def test_benign_mentions_do_not_fire_with_overeager_llm(text):
    """An LLM that cries wolf with an invented quote gets capped below the fire threshold."""
    llm = FakeLLM({"risk": 0.9, "patterns": [{"id": "safe_account", "u": 0, "quote": "move my money to a safe account"}]})
    r = await FraudDetector(llm).analyze(None, ctx_from([(0, text)]))
    assert r.score < 0.5 and r.details["patterns"] == []


def test_gift_card_demand_still_fires():
    a = keyword_assess([(0, "They want me to pay with Google Play gift cards and read the numbers on the back.")])
    assert a.score >= 0.6 and a.evidence[0].id == "gift_cards"
