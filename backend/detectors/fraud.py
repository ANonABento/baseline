"""Fraud / social-engineering analyzer over the rolling transcript.

Sends the last N utterances (numbered by utterance id) plus a compact playbook (id, name,
one line) to the LLM provider (Nebius / NVIDIA / Ollama via the OpenAI-compatible provider,
or the deterministic StubLLM) and parses its JSON. Every LLM-claimed pattern must come with
a quote that is actually in the transcript (validated + mapped to the right utterance id);
with no surviving evidence the score is capped below the fire threshold. If the LLM errors,
times out or returns unparseable output, falls back to the keyword/regex matcher over
kb/fraud_playbook.json, so the demo works with no LLM at all.

DetectorResult.details (contract with the frontend's FraudEvidence / Transcript):
    {"patterns": [{"id", "name", "severity": "low"|"medium"|"high", "quote", "utterance_id",
                   "source", "suggested_agent_action", "say_this"?}],
     "engine": "llm" | "keywords", "model": str | None,
     "citations": [{"pattern_id", "name", "source"}],   # consumed by fusion -> AlertEvent
     "suggested_action": str}                             # consumed by fusion -> AlertEvent
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from core import CallContext, Utterance
from detectors.base import Detector
from detectors.fraud_rules import (
    NO_EVIDENCE_SCORE_CAP,
    FraudAssessment,
    Utt,
    as_utterances,
    default_playbook,
    keyword_assess,
    parse_llm_fraud_json,
    playbook_by_id,
    summarize_reason,
    validate_llm_patterns,
)
from events import DetectorResult
from providers.base import LLMProvider

log = logging.getLogger(__name__)

DEFAULT_CONTEXT_UTTERANCES = 16
MAX_UTTERANCE_CHARS = 400  # per line in the prompt; keeps latency bounded on run-on STT output

SYSTEM_PROMPT = """You are a fraud analyst assisting a bank call-center agent live. You see the CALLER's side of the call as numbered lines [u<id>]. Decide whether the caller's words match patterns from the playbook (account takeover, impersonation scams, a customer being scammed or coached).
Rules:
- Use only playbook ids. For each pattern give the line number u and a short quote copied EXACTLY from that line (max 20 words).
- Judge only what was said; nothing about voice or identity.
- Benign requests that merely mention wires, transfers, gift cards, passwords or disputes are NOT fraud (e.g. disputing a wire they don't recognize, asking about a gift card they bought, resetting a password). Then return risk <= 0.2 and no patterns.
- verification_evasion: dodging identity/security questions, excuses, or pushing urgency right when asked to verify.
- coached_customer: relaying someone else's instructions ("he says I need to", "they told me not to tell you", "the man on the other line said").
- risk = probability (0-1) this call is fraud or the customer is being scammed. No quote, no risk.
Reply with JSON only, no prose:
{"risk":0.0,"confidence":0.0,"patterns":[{"id":"","u":0,"quote":""}],"reason":"<=20 words"}"""


def playbook_prompt() -> str:
    return "\n".join(f"- {p.id}: {p.name}. {p.one_liner}" for p in default_playbook())


def format_transcript(utts: Sequence[Utt]) -> str:
    lines = []
    for uid, text in utts:
        t = " ".join(text.split())
        if len(t) > MAX_UTTERANCE_CHARS:
            t = t[-MAX_UTTERANCE_CHARS:]
        lines.append(f"[u{uid}] {t}")
    return "\n".join(lines)


def build_user_prompt(transcript: str | Sequence[Utt]) -> str:
    utts = as_utterances(transcript)
    return f"Playbook:\n{playbook_prompt()}\n\nCaller transcript:\n<transcript>\n{format_transcript(utts)}\n</transcript>"


def _context_window_default() -> int:
    try:
        from settings import get_settings

        return int(get_settings().llm_context_utterances)
    except Exception:  # settings unavailable in some test setups
        return DEFAULT_CONTEXT_UTTERANCES


class FraudDetector(Detector):
    name = "fraud"
    requires_text = True

    def __init__(self, llm: LLMProvider | None = None, timeout_s: float = 3.0, max_utterances: int | None = None):
        self.llm = llm
        self.timeout_s = timeout_s
        self.max_utterances = max_utterances or _context_window_default()

    def _finalize_llm(self, parsed: FraudAssessment, utts: list[Utt]) -> FraudAssessment:
        evidence = validate_llm_patterns(parsed.raw_patterns, utts)
        score = parsed.score
        if not evidence:
            score = min(score, NO_EVIDENCE_SCORE_CAP)
        parsed.score = round(score, 3)
        parsed.evidence = evidence
        parsed.pattern_ids = [e.id for e in evidence]
        parsed.reason = summarize_reason(evidence)
        parsed.suggested_action = evidence[0].suggested_agent_action if evidence else ""
        parsed.model = getattr(self.llm, "model", None)
        return parsed

    async def assess(self, transcript: str | Sequence[Utt]) -> FraudAssessment:
        """`transcript` is either a plain string (one utterance, id 0) or (utterance_id, text)
        pairs. LLM sees the last `max_utterances`; the keyword fallback scans everything given."""
        utts = as_utterances(transcript)
        if not utts:
            return keyword_assess("")
        if self.llm is not None:
            window = utts[-self.max_utterances :]
            try:
                raw = await asyncio.wait_for(
                    self.llm.complete(SYSTEM_PROMPT, build_user_prompt(window)), timeout=self.timeout_s
                )
                parsed = parse_llm_fraud_json(raw, known_ids={p.id for p in default_playbook()})
                if parsed is not None:
                    a = self._finalize_llm(parsed, window)
                    if self.llm.is_stub:
                        a.method, a.model = "keyword", None
                    return a
                log.warning("LLM output unparseable, falling back to keywords: %r", (raw or "")[:200])
            except Exception as e:  # network, timeout, auth...
                log.warning("LLM call failed (%r), falling back to keywords", e)
        return keyword_assess(utts)

    async def analyze(self, utt: Utterance, ctx: CallContext) -> DetectorResult:
        utts = [(u.id, u.text) for u in ctx.utterances if u.text and u.text.strip()]
        a = await self.assess(utts)
        return result_from_assessment(a, self.name)


def result_from_assessment(a: FraudAssessment, signal: str = "fraud") -> DetectorResult:
    pb = playbook_by_id()
    citations = [{"pattern_id": e.id, "name": e.name, "source": e.source} for e in a.evidence]
    # Keyword patterns matched without a locatable quote (shouldn't happen) still get cited.
    cited = {c["pattern_id"] for c in citations}
    citations += [
        {"pattern_id": pid, "name": pb[pid].name, "source": pb[pid].source_url}
        for pid in a.pattern_ids
        if pid in pb and pid not in cited
    ]
    action = a.suggested_action or (a.evidence[0].suggested_agent_action if a.evidence else "")
    return DetectorResult(
        signal=signal,
        score=max(0.0, min(1.0, a.score)),
        confidence=max(0.0, min(1.0, a.confidence)),
        reason=a.reason,
        details={
            "patterns": [e.to_dict() for e in a.evidence],
            "engine": a.engine,
            "model": a.model if a.engine == "llm" else None,
            "citations": citations,
            "suggested_action": action,
        },
    )
