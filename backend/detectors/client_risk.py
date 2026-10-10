"""Client-side risk: what the PROTECTED CLIENT is saying (live calls, role client).

Baseline runs on the client's phone too, so besides judging the caller it can notice the
moment the client is about to hand something over. Fast regex rules, no LLM (< 1 ms).

Kinds (strongest first):
  secret      about to share a secret: one-time / verification code, card number, PIN, SSN,
              CVV, account or routing number, password, remote-access code; "let me get my
              card"; or reading out a digit string right after the caller asked for a code /
              card / number (`caller_context`).
  compliance  going along with the script: "which store", "I'll buy the gift cards", "I'll go to
              the bank / ATM", "I won't tell anyone", "I'll send / transfer / wire it", installing
              remote-access software.

Emits DetectorResult(signal="client"): a SOFT signal. Fusion lets it escalate caution -> high
only together with a hard caller signal (speaker / spoof / fraud). details:
    {"kind": "secret"|"compliance"|None, "reason_id": str|None, "matches": [str], "quote": str}
`reason_id` is one of: share_code, share_card, share_pin, share_ssn, share_account, share_password,
share_remote_code, reading_digits, get_card, gift_cards, go_to_bank, secrecy_promise, send_money,
install_remote.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from events import DetectorResult

_NUM_WORDS = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)"
# >= 4 digits, as numerals (optionally separated) or spelled out ("four one two seven")
_DIGITS = re.compile(rf"(?:\d[\s-]?){{4,}}|(?:\b{_NUM_WORDS}\b[\s,.-]*){{4,}}", re.I)
_SHORT_DIGITS = re.compile(rf"(?:\d[\s-]?){{3,}}|(?:\b{_NUM_WORDS}\b[\s,.-]*){{3,}}", re.I)

# caller lines that ask for something the client must never read out
_CALLER_ASKS = re.compile(
    r"\b(code|passcode|pin|card number|number on the (front|back)|digits|cvv|security number|social security|"
    r"account number|routing|password|read (me|it|them|that)|access code)\b", re.I)


@dataclass(frozen=True)
class Rule:
    reason_id: str
    kind: str  # secret | compliance
    pattern: re.Pattern
    label: str


def _r(p: str) -> re.Pattern:
    return re.compile(p, re.I)


RULES: tuple[Rule, ...] = (
    Rule("share_code", "secret",
         _r(r"\b(the|my|that|this)\s+(one[- ]time\s+|verification\s+|security\s+|6[- ]digit\s+|six[- ]digit\s+)?"
            r"(code|passcode|pass code)\s+(is|says|was)\b|\bcode\s+(is|says)\b|\bhere'?s\s+the\s+code\b|"
            r"\bi\s+(got|have|received)\s+(the|a|your)\s+(text|code)\b.{0,30}\b(it\s+)?(says|is)\b"),
         "About to read out a one-time code"),
    Rule("share_card", "secret",
         _r(r"\b(my\s+)?card\s+number\s+(is|was)\b|\b(the\s+)?numbers?\s+on\s+the\s+(back|front)\s+(is|are|says)\b|"
            r"\bexpir(es|ation)\s+(is|date\s+is)?\b|\b(cvv|cvc|security\s+code)\s+(is|was)\b"),
         "About to read out a card number"),
    Rule("share_pin", "secret", _r(r"\b(my\s+)?pin\s+(is|number\s+is)\b"), "About to share a PIN"),
    Rule("share_ssn", "secret",
         _r(r"\b(my\s+)?(social(\s+security)?(\s+number)?|ssn)\s+(is|number\s+is)\b"),
         "About to share a Social Security number"),
    Rule("share_account", "secret",
         _r(r"\b(my\s+)?(account|routing)\s+number\s+(is|was)\b"), "About to share an account number"),
    Rule("share_password", "secret",
         _r(r"\b(my\s+)?password\s+(is|was)\b"), "About to share a password"),
    Rule("share_remote_code", "secret",
         _r(r"\b(access|anydesk|teamviewer|session)\s+(code|id)\s+(is|says)\b"), "About to give remote access"),
    Rule("get_card", "secret",
         _r(r"\b(let\s+me|i'?ll|i\s+will|hold\s+on,?\s+i'?ll|i'?m\s+gonna|i'?m\s+going\s+to)\s+(get|grab|find|go\s+get)"
            r"\s+(my|the)\s+(card|wallet|debit\s+card|credit\s+card|bank\s+card|checkbook)\b|"
            r"\bi\s+have\s+(my|the)\s+card\s+(here|right\s+here|in\s+front)"),
         "Getting their card for the caller"),
    Rule("gift_cards", "compliance",
         _r(r"\b(which|what)\s+(store|kind\s+of\s+(gift\s+)?cards?|cards?)\b|"
            r"\b(i'?ll|i\s+will|i\s+can|i\s+could|let\s+me|okay,?\s+i'?ll)\s+(go\s+)?(buy|get|pick\s+up)\s+(the\s+|some\s+)?"
            r"(gift\s+cards?|cards|itunes|google\s+play|apple)\b|\bhow\s+many\s+(gift\s+)?cards\b|"
            r"\b(bitcoin|crypto)\s+atm\b.{0,20}\b(i'?ll|where)\b"),
         "Agreeing to pay with gift cards"),
    Rule("go_to_bank", "compliance",
         _r(r"\b(i'?ll|i\s+will|i\s+can|let\s+me|i'?m\s+going\s+to|i'?m\s+gonna)\s+(go\s+)?(to\s+)?(the\s+)?"
            r"(bank|atm|branch|store|walmart|target|best\s+buy|cvs)\b|\b(i'?ll|i\s+will)\s+(go|drive|head)\s+(there|now)\b"),
         "Agreeing to go withdraw or buy"),
    Rule("secrecy_promise", "compliance",
         _r(r"\b(i\s+won'?t|i\s+will\s+not|i\s+promise\s+(i\s+won'?t|not\s+to)|i\s+wo\s*n'?t)\s+(tell|say|mention)\b|"
            r"\bwon'?t\s+tell\s+(anyone|anybody|mom|your\s+mom|her|him|them)\b|\bour\s+secret\b|\bi\s+promise\b"),
         "Promising to keep it secret"),
    Rule("send_money", "compliance",
         _r(r"\b(i'?ll|i\s+will|i\s+can|let\s+me|okay,?\s+i'?ll)\s+(send|transfer|wire|move|pay|zelle|venmo)\b|"
            r"\bhow\s+much\s+(do\s+you|should\s+i|is\s+it)\b|\bwhere\s+(do|should)\s+i\s+(send|wire|transfer)\b"),
         "Agreeing to send money"),
    Rule("install_remote", "compliance",
         _r(r"\b(i'?ll|i\s+will|let\s+me|okay,?\s+i'?ll|i'?m)\s+(download|install|downloading|installing|open|opening)\b"
            r".{0,30}\b(anydesk|teamviewer|quick\s*assist|app|software|program|computer)\b"),
         "Installing remote-access software"),
)

KIND_SCORE = {"secret": (0.9, 0.85), "compliance": (0.65, 0.75)}
NO_RISK = (0.05, 0.5)


def caller_asked_for_secret(caller_lines: Sequence[str]) -> bool:
    return any(_CALLER_ASKS.search(t or "") for t in caller_lines)


def assess(text: str, caller_context: Sequence[str] = ()) -> DetectorResult:
    """Score one client utterance. `caller_context`: the caller's most recent line(s)."""
    t = " ".join((text or "").split())
    hits: list[Rule] = [r for r in RULES if r.pattern.search(t)]
    digits = _DIGITS.search(t) or (_SHORT_DIGITS.search(t) if caller_asked_for_secret(caller_context) else None)
    if digits and caller_asked_for_secret(caller_context):
        hits.insert(0, Rule("reading_digits", "secret", _DIGITS, "Reading out digits the caller asked for"))
    elif digits and not hits and re.search(r"\b(code|card|pin|number)\b", t, re.I):
        hits.append(Rule("reading_digits", "secret", _DIGITS, "Reading out digits"))
    if not hits:
        score, conf = NO_RISK
        return DetectorResult(signal="client", score=score, confidence=conf, reason="Nothing risky in what you said",
                              details={"kind": None, "reason_id": None, "matches": [], "quote": ""})
    hits.sort(key=lambda r: r.kind != "secret")  # secrets first, stable otherwise
    top = hits[0]
    score, conf = KIND_SCORE[top.kind]
    if len({h.reason_id for h in hits}) > 1:
        score = min(1.0, score + 0.05)
    m = top.pattern.search(t) if top.reason_id != "reading_digits" else digits
    quote = m.group(0).strip() if m else ""
    return DetectorResult(
        signal="client", score=round(score, 3), confidence=conf, reason=top.label,
        details={"kind": top.kind, "reason_id": top.reason_id,
                 "matches": list(dict.fromkeys(h.reason_id for h in hits)), "quote": quote},
    )
