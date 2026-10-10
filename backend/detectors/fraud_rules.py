"""Pure helpers for the fraud analyzer: playbook loading, keyword/regex matching and a
robust parser for LLM JSON output. No provider imports (keeps import graph acyclic)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

PLAYBOOK_PATH = Path(__file__).resolve().parent.parent / "kb" / "fraud_playbook.json"


# ---------------------------------------------------------------- playbook

@dataclass
class Pattern:
    id: str
    name: str
    category: str
    description: str
    severity: float
    suggested_agent_action: str
    source: dict[str, str]
    groups: list[list[re.Pattern[str]]]  # all groups must hit (single group for `triggers`)
    group_phrases: list[list[str]] = field(default_factory=list)


def normalize(text: str) -> str:
    """Lowercase, drop apostrophes (don't -> dont), turn other punctuation into spaces
    (keeps $ and digits/commas inside numbers)."""
    t = text.lower().replace("’", "'").replace("'", "")
    t = re.sub(r"[^a-z0-9$,\s]", " ", t)
    t = re.sub(r",(?!\d)", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _compile(trigger: str) -> re.Pattern[str]:
    if trigger.startswith("re:"):
        return re.compile(trigger[3:])
    words = normalize(trigger).split()
    return re.compile(r"\b" + r"\s+".join(re.escape(w) for w in words) + r"\b")


def load_playbook(path: Path = PLAYBOOK_PATH) -> list[Pattern]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[Pattern] = []
    for p in data["patterns"]:
        phrase_groups = p["requires_all"] if p.get("requires_all") else [p["triggers"]]
        out.append(
            Pattern(
                id=p["id"],
                name=p["name"],
                category=p.get("category", ""),
                description=p.get("description", ""),
                severity=float(p["severity"]),
                suggested_agent_action=p.get("suggested_agent_action", ""),
                source=p.get("source", {}),
                groups=[[_compile(t) for t in g] for g in phrase_groups],
                group_phrases=phrase_groups,
            )
        )
    return out


@lru_cache
def default_playbook() -> tuple[Pattern, ...]:
    return tuple(load_playbook())


def playbook_by_id() -> dict[str, Pattern]:
    return {p.id: p for p in default_playbook()}


# ---------------------------------------------------------------- keyword matcher

@dataclass
class PatternMatch:
    pattern: Pattern
    hits: list[str]
    score: float


@dataclass
class FraudAssessment:
    score: float
    confidence: float
    pattern_ids: list[str]
    reason: str
    suggested_action: str = ""
    matched_phrases: dict[str, list[str]] = field(default_factory=dict)
    method: str = "keyword"


def match_patterns(text: str, patterns: tuple[Pattern, ...] | list[Pattern] | None = None) -> list[PatternMatch]:
    patterns = patterns if patterns is not None else default_playbook()
    norm = normalize(text)
    matches: list[PatternMatch] = []
    for p in patterns:
        hits: list[str] = []
        ok = True
        for group in p.groups:
            group_hits = [m.group(0) for rx in group for m in [rx.search(norm)] if m]
            if not group_hits:
                ok = False
                break
            hits.extend(group_hits)
        if not ok:
            continue
        hits = list(dict.fromkeys(hits))
        # Multiple independent phrase hits make us a bit more sure.
        score = p.severity if len(hits) >= 2 else p.severity * 0.85
        matches.append(PatternMatch(pattern=p, hits=hits, score=score))
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


def combine(scores: list[float]) -> float:
    """Noisy-OR: independent evidence accumulates but never exceeds 1."""
    prod = 1.0
    for s in scores:
        prod *= 1.0 - max(0.0, min(1.0, s))
    return 1.0 - prod


def keyword_assess(text: str, patterns: tuple[Pattern, ...] | list[Pattern] | None = None) -> FraudAssessment:
    if not text.strip():
        return FraudAssessment(0.0, 0.0, [], "No transcript yet.")
    matches = match_patterns(text, patterns)
    if not matches:
        return FraudAssessment(0.0, 0.5, [], "No known fraud pattern in the transcript so far.")
    score = combine([m.score for m in matches])
    top = matches[0].pattern
    reason = "Matches " + "; ".join(
        f"{m.pattern.name} (\"{m.hits[0]}\")" for m in matches[:3]
    )
    return FraudAssessment(
        score=round(score, 3),
        confidence=0.6,
        pattern_ids=[m.pattern.id for m in matches],
        reason=reason,
        suggested_action=top.suggested_agent_action,
        matched_phrases={m.pattern.id: m.hits for m in matches},
    )


# ---------------------------------------------------------------- LLM output parsing

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_object(text: str) -> str | None:
    """First balanced {...} block, honouring strings."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None


def _loads_lenient(blob: str) -> Any:
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        pass
    fixed = re.sub(r",\s*([}\]])", r"\1", blob)  # trailing commas
    fixed = re.sub(r"\bTrue\b", "true", fixed)
    fixed = re.sub(r"\bFalse\b", "false", fixed)
    fixed = re.sub(r"\bNone\b", "null", fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    if "'" in fixed and '"' not in fixed:
        try:
            return json.loads(fixed.replace("'", '"'))
        except json.JSONDecodeError:
            pass
    return None


def _to_unit(v: Any, default: float | None = None) -> float | None:
    """Coerce 0.8 / "0.8" / "80%" / 80 / "high" into [0, 1]."""
    if v is None or isinstance(v, bool):
        return default
    if isinstance(v, str):
        s = v.strip().lower()
        words = {"none": 0.0, "low": 0.25, "medium": 0.5, "moderate": 0.5, "high": 0.8, "very high": 0.95, "critical": 0.95}
        if s in words:
            return words[s]
        pct = s.endswith("%")
        try:
            f = float(s.rstrip("%").strip())
        except ValueError:
            return default
        if pct:
            f /= 100.0
        v = f
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:  # NaN
        return default
    if 1.0 < f <= 100.0:
        f /= 100.0
    return max(0.0, min(1.0, f))


def parse_llm_fraud_json(raw: str | None, known_ids: set[str] | None = None) -> FraudAssessment | None:
    """Parse the LLM's fraud verdict. Returns None if nothing usable could be recovered
    (caller then falls back to the keyword matcher). Expected shape:
    {"fraud_score": 0-1, "confidence": 0-1, "patterns": ["id", ...], "reason": str,
     "suggested_action": str}"""
    if not raw or not isinstance(raw, str):
        return None
    candidates: list[str] = [m.group(1) for m in _FENCE.finditer(raw)] + [raw]
    data: Any = None
    for cand in candidates:
        blob = _extract_object(cand)
        if blob is None:
            continue
        data = _loads_lenient(blob)
        if isinstance(data, dict):
            break
        data = None
    if not isinstance(data, dict):
        return None

    score = _to_unit(data.get("fraud_score", data.get("score", data.get("risk"))))
    if score is None:
        return None
    confidence = _to_unit(data.get("confidence"), default=0.7)
    pats = data.get("patterns", data.get("pattern_ids", []))
    if isinstance(pats, str):
        pats = [pats]
    if not isinstance(pats, list):
        pats = []
    ids: list[str] = []
    for p in pats:
        pid = p.get("id") if isinstance(p, dict) else p
        if isinstance(pid, str) and (known_ids is None or pid in known_ids):
            ids.append(pid)
    reason = data.get("reason", "")
    action = data.get("suggested_action", "")
    return FraudAssessment(
        score=round(score, 3),
        confidence=round(confidence if confidence is not None else 0.7, 3),
        pattern_ids=list(dict.fromkeys(ids)),
        reason=str(reason) if reason else "LLM flagged the conversation.",
        suggested_action=str(action) if action else "",
        method="llm",
    )
