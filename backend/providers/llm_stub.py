"""Deterministic, offline LLM stand-in. It pulls the numbered transcript out of the prompt
(`[u<id>] text` lines between <transcript> tags) and answers with keyword-matcher output in
the same JSON shape a real LLM is asked for, so the fraud detector's parse + quote
validation path is always exercised."""

from __future__ import annotations

import json
import re

from detectors.fraud_rules import keyword_assess
from providers.base import LLMProvider

_TRANSCRIPT = re.compile(r"<transcript>(.*?)</transcript>", re.DOTALL)
_LINE = re.compile(r"^\s*\[u(\d+)\]\s?(.*)$")


def parse_numbered_transcript(block: str) -> list[tuple[int, str]]:
    utts: list[tuple[int, str]] = []
    for line in block.splitlines():
        m = _LINE.match(line)
        if m:
            utts.append((int(m.group(1)), m.group(2)))
        elif line.strip() and utts:  # continuation line
            uid, text = utts[-1]
            utts[-1] = (uid, f"{text} {line.strip()}")
    return utts


class StubLLM(LLMProvider):
    name = "stub"
    is_stub = True
    model = None

    async def complete(self, system: str, user: str, *, json_mode: bool = True) -> str:
        m = _TRANSCRIPT.search(user)
        block = m.group(1) if m else user
        utts = parse_numbered_transcript(block) or block
        a = keyword_assess(utts)
        return json.dumps(
            {
                "risk": a.score,
                "confidence": a.confidence,
                "patterns": [{"id": e.id, "u": e.utterance_id, "quote": e.quote} for e in a.evidence],
                "reason": a.reason,
            }
        )
