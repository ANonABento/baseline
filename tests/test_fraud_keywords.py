import json

import pytest

from detectors.fraud_rules import PLAYBOOK_PATH, default_playbook, keyword_assess, match_patterns, normalize


def ids(text):
    return {m.pattern.id for m in match_patterns(text)}


def test_playbook_is_well_formed():
    data = json.loads(PLAYBOOK_PATH.read_text())
    pats = data["patterns"]
    assert 15 <= len(pats) <= 40
    seen = set()
    for p in pats:
        assert p["id"] not in seen
        seen.add(p["id"])
        for key in ("name", "description", "suggested_agent_action", "source", "severity"):
            assert p.get(key), (p["id"], key)
        assert p["source"]["url"].startswith("https://")
        assert 0 < p["severity"] <= 1
        assert p.get("triggers") or p.get("requires_all")
    assert len(default_playbook()) == len(pats)


def test_normalize():
    assert normalize("Don’t TELL anyone!!") == "dont tell anyone"
    assert normalize("$9,000.") == "$9,000"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I need to change my phone number and then wire $9,000 to a new account.", "ato_contact_change_then_money"),
        ("My grandson was arrested and needs bail money.", "grandparent_bail"),
        ("They want me to pay with Google Play gift cards and read the numbers on the back.", "gift_cards"),
        ("I have to put cash into a bitcoin ATM.", "crypto_payment"),
        ("The IRS said there is a warrant for my arrest for back taxes.", "government_impersonation"),
        ("Your fraud department told me to move my money to a safe account.", "safe_account"),
        ("The man had me install AnyDesk so he could fix it.", "remote_access"),
        ("He said don't tell the bank about this.", "secrecy"),
        ("They're telling me what to say, they are on the other line.", "coached_customer"),
    ],
)
def test_patterns_detected(text, expected):
    assert expected in ids(text)


def test_takeover_script_scores_high():
    a = keyword_assess("Please update my email address. Then I want to transfer 9,000 dollars today, it's urgent.")
    assert a.score >= 0.8
    assert a.pattern_ids[0] == "ato_contact_change_then_money"
    assert a.suggested_action
    assert a.method == "keyword"


@pytest.mark.parametrize(
    "benign",
    [
        "Hi, I'd like to check my balance and ask about the interest rate on savings.",
        "I'd like to set up my monthly wire transfer to my landlord like I always do.",
        "Can I order a new debit card? Mine is worn out.",
        "I moved last month, so I'd like to update my address please.",
    ],
)
def test_benign_calls_do_not_fire(benign):
    a = keyword_assess(benign)
    assert a.score < 0.5, (benign, a.reason)


def test_empty_transcript():
    a = keyword_assess("   ")
    assert a.score == 0.0 and a.confidence == 0.0


def test_every_pattern_has_a_short_say_this_line():
    data = json.loads(PLAYBOOK_PATH.read_text())
    for p in data["patterns"]:
        line = p.get("say_this", "")
        assert line and len(line) <= 160 and line[-1] in ".?!", p["id"]
        assert "scam" not in line.lower().split()[:3], p["id"]  # opens calmly, not with an accusation


def test_say_this_surfaces_in_evidence_dicts():
    from detectors.fraud import result_from_assessment

    a = keyword_assess("My grandson was arrested and needs bail money.")
    pats = result_from_assessment(a).details["patterns"]
    assert pats and pats[0]["id"] == "grandparent_bail"
    assert pats[0]["say_this"].startswith("Before we send anything")
