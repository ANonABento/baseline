"""Pure helpers for the fraud analyzer: playbook loading, keyword/regex matching, evidence
(verbatim quotes mapped to utterance ids), validation of LLM-claimed evidence, and a
robust parser for LLM JSON output. No provider imports (keeps import graph acyclic).

Evidence contract (what `FraudDetector` puts in `DetectorResult.details["patterns"]`):
    {"id", "name", "severity": "low"|"medium"|"high", "quote" (verbatim, <=160 chars),
     "utterance_id", "source" (URL), "suggested_agent_action"}
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

PLAYBOOK_PATH = Path(__file__).resolve().parent.parent / "kb" / "fraud_playbook.json"

MAX_QUOTE_CHARS = 160
# With no validated evidence the fraud score is capped here (below the fusion fire threshold):
# "no quote, no alarm" is our main false-positive control for the LLM path.
NO_EVIDENCE_SCORE_CAP = 0.35

Utt = tuple[int, str]  # (utterance_id, text)


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

    @property
    def severity_label(self) -> str:
        return severity_label(self.severity)

    @property
    def source_url(self) -> str:
        return self.source.get("url", "")

    @property
    def one_liner(self) -> str:
        """First sentence of the description, for the compact LLM prompt."""
        first = re.split(r"(?<=[.!?])\s", self.description.strip(), maxsplit=1)[0]
        return first if len(first) <= 140 else first[:137].rsplit(" ", 1)[0] + "..."


def severity_label(sev: float) -> str:
    return "low" if sev < 0.4 else "medium" if sev < 0.7 else "high"


def normalize(text: str) -> str:
    """Lowercase, drop apostrophes (don't -> dont), turn other punctuation into spaces
    (keeps $ and digits/commas inside numbers)."""
    t = text.lower().replace("’", "'").replace("'", "")
    t = re.sub(r"[^a-z0-9$,\s]", " ", t)
    t = re.sub(r",(?!\d)", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_KEEP = re.compile(r"[a-z0-9$,\s]")


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Same output as `normalize(text)`, plus for every output char the index of the
    original char it came from, so a match in normalized space maps back to a verbatim span."""
    chars: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        for c in ch.lower():
            if c in "'’":
                continue
            chars.append(c if _KEEP.match(c) else " ")
            idx.append(i)
    for j, c in enumerate(chars):
        if c == "," and not (j + 1 < len(chars) and chars[j + 1].isdigit()):
            chars[j] = " "
    out: list[str] = []
    out_idx: list[int] = []
    for c, i in zip(chars, idx):
        if c.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                out_idx.append(i)
        else:
            out.append(c)
            out_idx.append(i)
    if out and out[-1] == " ":
        out.pop()
        out_idx.pop()
    return "".join(out), out_idx


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


# ---------------------------------------------------------------- transcript helpers

def as_utterances(transcript: str | Sequence[Utt] | None) -> list[Utt]:
    """Accept a plain transcript string (treated as utterance 0) or (id, text) pairs."""
    if transcript is None:
        return []
    if isinstance(transcript, str):
        return [(0, transcript)] if transcript.strip() else []
    return [(int(i), t) for i, t in transcript if t and t.strip()]


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    s = start
    while s > 0 and not (text[s - 1] in ".!?" and (s >= len(text) or text[s].isspace())):
        s -= 1
    e = end
    while e < len(text) and text[e - 1 : e] not in (".", "!", "?"):
        e += 1
    while s < e and text[s].isspace():
        s += 1
    return s, e


def quote_around(text: str, start: int, end: int, max_len: int = MAX_QUOTE_CHARS) -> str:
    """Verbatim snippet of `text` containing [start, end): the enclosing sentence if it fits,
    otherwise a word-aligned window around the span. Always a substring of `text`."""
    s, e = _sentence_bounds(text, start, end)
    if e - s <= max_len:
        return text[s:e].strip()
    span = end - start
    if span >= max_len:
        s, e = start, start + max_len
    else:
        pad = (max_len - span) // 2
        s = max(0, start - pad)
        e = min(len(text), s + max_len)
        s = max(0, e - max_len)
    # snap inward to word boundaries without cutting the matched span
    if s > 0 and not text[s - 1].isspace():
        nxt = text.find(" ", s, start + 1)
        if nxt != -1:
            s = nxt + 1
    if e < len(text) and not text[e].isspace():
        prv = text.rfind(" ", max(end, s), e)
        if prv != -1:
            e = prv
    return text[s:e].strip()


@dataclass
class Evidence:
    id: str
    name: str
    severity: str
    quote: str
    utterance_id: int
    source: str
    suggested_agent_action: str
    severity_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "severity": self.severity,
            "quote": self.quote,
            "utterance_id": self.utterance_id,
            "source": self.source,
            "suggested_agent_action": self.suggested_agent_action,
        }


def make_evidence(p: Pattern, quote: str, utterance_id: int) -> Evidence:
    return Evidence(
        id=p.id,
        name=p.name,
        severity=p.severity_label,
        quote=quote[:MAX_QUOTE_CHARS].strip(),
        utterance_id=int(utterance_id),
        source=p.source_url,
        suggested_agent_action=p.suggested_agent_action,
        severity_score=p.severity,
    )


# ---------------------------------------------------------------- keyword matcher

@dataclass
class Hit:
    group: int
    utterance_id: int
    phrase: str  # normalized matched text
    start: int  # verbatim span in that utterance's text
    end: int


@dataclass
class PatternMatch:
    pattern: Pattern
    hits: list[str]
    score: float
    located: list[Hit] = field(default_factory=list)

    def best_evidence(self, utts: Sequence[Utt]) -> Evidence | None:
        """Quote the utterance covering the most trigger groups (ties: more hits, then latest)."""
        if not self.located:
            return None
        by_utt: dict[int, list[Hit]] = {}
        for h in self.located:
            by_utt.setdefault(h.utterance_id, []).append(h)
        uid = max(by_utt, key=lambda u: (len({h.group for h in by_utt[u]}), len(by_utt[u]), u))
        text = dict(utts)[uid]
        first = min(by_utt[uid], key=lambda h: h.start)
        return make_evidence(self.pattern, quote_around(text, first.start, first.end), uid)


@dataclass
class FraudAssessment:
    score: float
    confidence: float
    pattern_ids: list[str]
    reason: str
    suggested_action: str = ""
    matched_phrases: dict[str, list[str]] = field(default_factory=dict)
    method: str = "keyword"  # "llm" | "keyword"
    evidence: list[Evidence] = field(default_factory=list)
    model: str | None = None
    raw_patterns: list[Any] = field(default_factory=list)  # LLM-claimed items, pre-validation

    @property
    def engine(self) -> str:
        return "llm" if self.method == "llm" else "keywords"


def _norm_utts(utts: Sequence[Utt]) -> list[tuple[int, str, str, list[int]]]:
    out = []
    for uid, text in utts:
        n, m = normalize_with_map(text)
        out.append((uid, text, n, m))
    return out


def match_patterns(
    text: str | Sequence[Utt], patterns: tuple[Pattern, ...] | list[Pattern] | None = None
) -> list[PatternMatch]:
    """A pattern matches when every trigger group hits somewhere in the call (groups may be
    satisfied by different utterances, e.g. contact change early, wire later)."""
    patterns = patterns if patterns is not None else default_playbook()
    nutts = _norm_utts(as_utterances(text))
    matches: list[PatternMatch] = []
    for p in patterns:
        located: list[Hit] = []
        ok = True
        for gi, group in enumerate(p.groups):
            group_hits: list[Hit] = []
            for rx in group:
                for uid, _text, norm, nmap in nutts:
                    m = rx.search(norm)
                    if m and m.end() > m.start():
                        group_hits.append(Hit(gi, uid, m.group(0), nmap[m.start()], nmap[m.end() - 1] + 1))
            if not group_hits:
                ok = False
                break
            located.extend(group_hits)
        if not ok:
            continue
        hits = list(dict.fromkeys(h.phrase for h in located))
        # Multiple independent phrase hits make us a bit more sure.
        score = p.severity if len(hits) >= 2 else p.severity * 0.85
        matches.append(PatternMatch(pattern=p, hits=hits, score=score, located=located))
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


def combine(scores: list[float]) -> float:
    """Noisy-OR: independent evidence accumulates but never exceeds 1."""
    prod = 1.0
    for s in scores:
        prod *= 1.0 - max(0.0, min(1.0, s))
    return 1.0 - prod


def _short(q: str, n: int = 90) -> str:
    return q if len(q) <= n else q[: n - 1].rsplit(" ", 1)[0] + "…"


def summarize_reason(evidence: Sequence[Evidence]) -> str:
    """One short human sentence naming the top pattern."""
    if not evidence:
        return "No known fraud pattern in the transcript so far."
    top = evidence[0]
    more = f" (+{len(evidence) - 1} more)" if len(evidence) > 1 else ""
    return f'{top.name}: caller said "{_short(top.quote)}"{more}.'


def order_evidence(evidence: Sequence[Evidence]) -> list[Evidence]:
    """Highest playbook severity first; stable otherwise. One entry per pattern id."""
    seen: set[str] = set()
    uniq = []
    for e in evidence:
        if e.id not in seen:
            seen.add(e.id)
            uniq.append(e)
    return sorted(uniq, key=lambda e: -e.severity_score)


def keyword_assess(
    text: str | Sequence[Utt], patterns: tuple[Pattern, ...] | list[Pattern] | None = None
) -> FraudAssessment:
    utts = as_utterances(text)
    if not utts:
        return FraudAssessment(0.0, 0.0, [], "No transcript yet.")
    matches = match_patterns(utts, patterns)
    if not matches:
        return FraudAssessment(0.0, 0.5, [], summarize_reason([]))
    score = combine([m.score for m in matches])
    evidence = order_evidence([e for m in matches if (e := m.best_evidence(utts)) is not None])
    return FraudAssessment(
        score=round(score, 3),
        confidence=0.6,
        pattern_ids=[m.pattern.id for m in matches],
        reason=summarize_reason(evidence),
        suggested_action=matches[0].pattern.suggested_agent_action,
        matched_phrases={m.pattern.id: m.hits for m in matches},
        evidence=evidence,
    )


# ---------------------------------------------------------------- LLM evidence validation

_TOKEN = re.compile(r"[a-z0-9$]+")


def _clean_quote(q: str) -> str:
    q = q.strip().strip("\"'“”‘’`").strip()
    return q


def find_quote(quote: str, utts: Sequence[Utt], prefer: int | None = None) -> tuple[int, str] | None:
    """Locate an LLM-claimed quote in the transcript (case/punctuation-insensitive) and
    return (utterance_id, verbatim snippet). Tries the claimed utterance first, then the
    others latest-first. Quotes with "..." elisions match on their longest fragment."""
    q = _clean_quote(quote or "")
    if not q:
        return None
    frags = [f for f in re.split(r"\.\.\.|…", q) if normalize(f)]
    if not frags:
        return None
    nq = normalize(max(frags, key=lambda f: len(normalize(f))))
    if len(nq) < 3:
        return None
    nutts = _norm_utts(utts)
    order = sorted(nutts, key=lambda t: (t[0] != prefer, -t[0]))
    for uid, text, norm, nmap in order:
        # word-boundary match so "ire" doesn't match inside "wire"
        m = re.search(r"(?<![a-z0-9$])" + re.escape(nq) + r"(?![a-z0-9$])", norm)
        if m:
            s, e = nmap[m.start()], nmap[m.end() - 1] + 1
            snippet = text[s:e] if e - s <= MAX_QUOTE_CHARS else quote_around(text, s, e)
            return uid, snippet.strip()
    return None


def _overlap_repair(quote: str, utts: Sequence[Utt], prefer: int | None) -> tuple[int, str] | None:
    """Paraphrased quote: pick the sentence (claimed utterance first) sharing >= 60% of the
    quote's words."""
    qt = set(_TOKEN.findall(normalize(quote or "")))
    if len(qt) < 3:
        return None
    best: tuple[float, int, str] | None = None
    for uid, text in sorted(utts, key=lambda t: (t[0] != prefer, -t[0])):
        for m in re.finditer(r"[^.!?]+[.!?]?", text):
            sent = m.group(0).strip()
            st = set(_TOKEN.findall(normalize(sent)))
            if not st:
                continue
            ov = len(qt & st) / len(qt)
            if ov >= 0.6 and (best is None or ov > best[0]):
                best = (ov, uid, quote_around(text, m.start(), m.end()))
        if best is not None and uid == prefer:
            break
    return (best[1], best[2]) if best else None


def _to_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+", v)
        return int(m.group(0)) if m else None
    return None


def validate_llm_patterns(
    items: Sequence[Any], utts: Sequence[Utt], playbook: dict[str, Pattern] | None = None
) -> list[Evidence]:
    """Turn LLM-claimed pattern items into trusted evidence. Unknown ids are dropped. The
    quote must exist in the transcript: exact (normalized) match first, then the keyword
    matcher's own quote for that pattern, then a word-overlap repair; otherwise dropped.
    utterance_id is always the utterance the quote was actually found in."""
    pb = playbook if playbook is not None else playbook_by_id()
    valid_ids = {u for u, _ in utts}
    out: list[Evidence] = []
    for item in items or []:
        if isinstance(item, str):
            pid, quote, claimed = item, "", None
        elif isinstance(item, dict):
            pid = item.get("id") or item.get("pattern_id") or item.get("pattern")
            quote = item.get("quote") or item.get("evidence") or ""
            claimed = _to_int(item.get("u", item.get("utterance_id", item.get("utterance"))))
        else:
            continue
        if not isinstance(pid, str) or pid not in pb:
            continue
        p = pb[pid]
        prefer = claimed if claimed in valid_ids else None
        found = find_quote(str(quote), utts, prefer) if quote else None
        if found is None:
            km = match_patterns(utts, [p])
            ev = km[0].best_evidence(utts) if km else None
            if ev is not None:
                found = (ev.utterance_id, ev.quote)
        if found is None and quote:
            found = _overlap_repair(str(quote), utts, prefer)
        if found is None:
            continue
        out.append(make_evidence(p, found[1], found[0]))
    return order_evidence(out)


# ---------------------------------------------------------------- LLM output parsing

_THINK = re.compile(r"<think>.*?(</think>|$)", re.DOTALL | re.IGNORECASE)
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
    (caller then falls back to the keyword matcher). Expected shape (see fraud.SYSTEM_PROMPT):
    {"risk": 0-1, "confidence": 0-1, "patterns": [{"id", "u", "quote"}], "reason": str}
    Also accepts fraud_score/score, bare id lists, fenced/chatty output, <think> blocks."""
    if not raw or not isinstance(raw, str):
        return None
    raw = _THINK.sub("", raw)
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

    score = _to_unit(data.get("risk", data.get("fraud_score", data.get("score"))))
    if score is None:
        return None
    confidence = _to_unit(data.get("confidence"), default=0.7)
    pats = data.get("patterns", data.get("pattern_ids", []))
    if isinstance(pats, (str, dict)):
        pats = [pats]
    if not isinstance(pats, list):
        pats = []
    ids: list[str] = []
    items: list[Any] = []
    for p in pats:
        pid = (p.get("id") or p.get("pattern_id")) if isinstance(p, dict) else p
        if isinstance(pid, str) and (known_ids is None or pid in known_ids):
            ids.append(pid)
            items.append(p)
    reason = data.get("reason", "")
    action = data.get("suggested_action", "")
    return FraudAssessment(
        score=round(score, 3),
        confidence=round(confidence if confidence is not None else 0.7, 3),
        pattern_ids=list(dict.fromkeys(ids)),
        reason=str(reason) if reason else "LLM flagged the conversation.",
        suggested_action=str(action) if action else "",
        method="llm",
        raw_patterns=items,
    )
