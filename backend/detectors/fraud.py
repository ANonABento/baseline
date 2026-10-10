"""Fraud / social-engineering analyzer over the rolling transcript.

Sends the transcript plus the playbook to the LLM provider (Nebius / NVIDIA / Ollama via
the OpenAI-compatible provider, or the deterministic StubLLM) and parses its JSON.
If the LLM errors, times out or returns unparseable output, falls back to the
keyword/regex matcher over kb/fraud_playbook.json, so the demo works with no LLM at all."""

from __future__ import annotations

import asyncio
import logging

from core import CallContext, Utterance
from detectors.base import Detector
from detectors.fraud_rules import (
    FraudAssessment,
    default_playbook,
    keyword_assess,
    parse_llm_fraud_json,
)
from events import DetectorResult
from providers.base import LLMProvider

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a fraud analyst assisting a bank call-center agent in real time.
You read the transcript of the CALLER's side of a phone call and decide whether it matches
known fraud or social-engineering patterns (account takeover, impersonation scams, coaching).
Only use the pattern ids from the playbook provided. Do not guess about voice or identity.
Benign requests that merely mention wires, transfers or gift cards are NOT fraud.
Respond with ONLY a JSON object:
{"fraud_score": <0-1>, "confidence": <0-1>, "patterns": [<pattern ids>],
 "reason": "<one sentence for the agent>", "suggested_action": "<one sentence>"}"""


def build_user_prompt(transcript: str) -> str:
    lines = [f"- {p.id}: {p.name}. {p.description}" for p in default_playbook()]
    return "Playbook:\n" + "\n".join(lines) + f"\n\n<transcript>{transcript}</transcript>"


class FraudDetector(Detector):
    name = "fraud"
    requires_text = True

    def __init__(self, llm: LLMProvider | None = None, timeout_s: float = 8.0):
        self.llm = llm
        self.timeout_s = timeout_s

    async def assess(self, transcript: str) -> FraudAssessment:
        if not transcript.strip():
            return keyword_assess("")
        if self.llm is not None:
            try:
                raw = await asyncio.wait_for(
                    self.llm.complete(SYSTEM_PROMPT, build_user_prompt(transcript)), timeout=self.timeout_s
                )
                parsed = parse_llm_fraud_json(raw, known_ids={p.id for p in default_playbook()})
                if parsed is not None:
                    if self.llm.is_stub:
                        parsed.method = "keyword"
                    return parsed
                log.warning("LLM output unparseable, falling back to keywords: %r", raw[:200])
            except Exception as e:  # network, timeout, auth...
                log.warning("LLM call failed (%r), falling back to keywords", e)
        return keyword_assess(transcript)

    async def analyze(self, utt: Utterance, ctx: CallContext) -> DetectorResult:
        a = await self.assess(ctx.transcript)
        pb = {p.id: p for p in default_playbook()}
        citations = [
            {"pattern_id": pid, "name": pb[pid].name, "source": pb[pid].source.get("url", "")}
            for pid in a.pattern_ids
            if pid in pb
        ]
        action = a.suggested_action or (pb[a.pattern_ids[0]].suggested_agent_action if a.pattern_ids else "")
        return DetectorResult(
            signal=self.name,
            score=a.score,
            confidence=a.confidence,
            reason=a.reason,
            details={
                "method": a.method,
                "patterns": a.pattern_ids,
                "matched_phrases": a.matched_phrases,
                "citations": citations,
                "suggested_action": action,
            },
        )
