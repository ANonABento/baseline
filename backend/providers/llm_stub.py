"""Deterministic, offline LLM stand-in. It pulls the transcript out of the prompt
(between <transcript> tags) and answers with keyword-matcher output in the same JSON
shape a real LLM is asked for, so the fraud detector's parse path is always exercised."""

from __future__ import annotations

import json
import re

from detectors.fraud_rules import keyword_assess
from providers.base import LLMProvider

_TRANSCRIPT = re.compile(r"<transcript>(.*?)</transcript>", re.DOTALL)


class StubLLM(LLMProvider):
    name = "stub"
    is_stub = True

    async def complete(self, system: str, user: str, *, json_mode: bool = True) -> str:
        m = _TRANSCRIPT.search(user)
        a = keyword_assess(m.group(1) if m else user)
        return json.dumps(
            {
                "fraud_score": a.score,
                "confidence": a.confidence,
                "patterns": a.pattern_ids,
                "reason": a.reason,
                "suggested_action": a.suggested_action,
            }
        )
