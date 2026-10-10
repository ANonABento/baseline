import asyncio

import pytest

from detectors.fraud import FraudDetector
from detectors.fraud_rules import parse_llm_fraud_json
from providers.base import LLMProvider
from providers.llm_stub import StubLLM

KNOWN = {"gift_cards", "grandparent_bail"}


def test_clean_json():
    a = parse_llm_fraud_json('{"fraud_score": 0.8, "confidence": 0.9, "patterns": ["gift_cards"], "reason": "r", "suggested_action": "s"}', KNOWN)
    assert a.score == 0.8 and a.confidence == 0.9 and a.pattern_ids == ["gift_cards"] and a.method == "llm"


@pytest.mark.parametrize(
    "raw",
    [
        '```json\n{"fraud_score": 0.7, "patterns": ["gift_cards"]}\n```',
        'Sure! Here is my analysis:\n{"fraud_score": 0.7, "patterns": ["gift_cards"]} Hope that helps.',
        '{"fraud_score": 0.7, "patterns": ["gift_cards"],}',  # trailing comma
        "{'fraud_score': 0.7, 'patterns': ['gift_cards']}",  # python-style quotes
        '{"fraud_score": "70%", "patterns": "gift_cards"}',  # percent string, bare string list
        '{"fraud_score": 70, "patterns": [{"id": "gift_cards"}]}',  # 0-100 scale, objects
        '{"reason": "uses {braces} in text", "fraud_score": 0.7, "patterns": ["gift_cards", "made_up_id"]}',
    ],
)
def test_malformed_but_recoverable(raw):
    a = parse_llm_fraud_json(raw, KNOWN)
    assert a is not None
    assert a.score == pytest.approx(0.7)
    assert a.pattern_ids == ["gift_cards"]


@pytest.mark.parametrize(
    "raw",
    [None, "", "I cannot help with that.", '{"fraud_score": ', '{"reason": "no score"}', "[1, 2, 3]",
     '{"fraud_score": "unknown"}', 12345],
)
def test_unrecoverable_returns_none(raw):
    assert parse_llm_fraud_json(raw, KNOWN) is None


def test_scores_clamped_and_words():
    assert parse_llm_fraud_json('{"fraud_score": 3.5}').score == 0.035  # 0-100 scale
    assert parse_llm_fraud_json('{"fraud_score": -1}').score == 0.0
    assert parse_llm_fraud_json('{"fraud_score": "high"}').score == 0.8


class GarbageLLM(LLMProvider):
    name = "garbage"

    async def complete(self, system, user, *, json_mode=True):
        return "lol not json"


class BoomLLM(LLMProvider):
    name = "boom"

    async def complete(self, system, user, *, json_mode=True):
        raise TimeoutError("simulated timeout")


class SlowLLM(LLMProvider):
    name = "slow"

    async def complete(self, system, user, *, json_mode=True):
        await asyncio.sleep(10)
        return "{}"


TAKEOVER = "Change my phone number, then wire 9,000 dollars to a new account right now."


@pytest.mark.parametrize("llm", [GarbageLLM(), BoomLLM(), None])
async def test_fraud_detector_falls_back_to_keywords(llm):
    a = await FraudDetector(llm).assess(TAKEOVER)
    assert a.method == "keyword"
    assert a.score >= 0.8


async def test_stub_llm_roundtrip():
    a = await FraudDetector(StubLLM()).assess(TAKEOVER)
    assert "ato_contact_change_then_money" in a.pattern_ids
    assert a.score >= 0.8


async def test_slow_llm_times_out_and_falls_back():
    a = await asyncio.wait_for(FraudDetector(SlowLLM(), timeout_s=0.05).assess(TAKEOVER), timeout=2)
    assert a.method == "keyword" and a.score >= 0.8
