"""Fusion: detector results -> Trust Score + alert level + reasons + suggested action.

- Each signal keeps a running risk (EMA for per-utterance audio signals; the fraud
  analyzer already looks at the whole rolling transcript, so its latest value is used).
- Effective risk per signal = score * confidence * weight. Signals are combined with a
  noisy-OR so independent evidence accumulates: risk = 1 - prod(1 - r_i).
- Trust Score = 100 * (1 - risk), smoothed with fast attack (drops quickly) / slow release.
- A signal "fires" when (on its smoothed values) score >= FIRE_THRESHOLD, confidence >=
  FIRE_MIN_CONFIDENCE and score * confidence >= MIN_EVIDENCE. The last rule keeps a single
  low-confidence blip (e.g. one noisy spoof window) from raising even a caution.
- Evidence latches for the call: once a signal has fired, its strongest reading stays in the
  alert (fraud patterns are merged by id), so the alert never loses its reasons when a
  smoothed score dips back under the threshold.
- Alert level: none (nothing fired), caution (one hard signal, or only the soft prosody
  signal), high (>= HIGH_MIN_HARD_SIGNALS independent hard signals among speaker / spoof /
  fraud have fired during the call). The level never de-escalates within a call.
- alert_if_changed() emits only on a material change: the level changes, or at the same
  level a NEW signal or NEW fraud pattern id joins the evidence. Re-worded reasons and score
  jitter do not produce new alert events.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from events import AlertEvent, AlertLevel, Citation, DetectorResult, TrustEvent

WEIGHTS: dict[str, float] = {"spoof": 0.9, "fraud": 0.85, "speaker": 0.7, "prosody": 0.3}
HARD_SIGNALS = ("speaker", "spoof", "fraud")
EMA_ALPHA: dict[str, float] = {"spoof": 0.6, "speaker": 0.6, "prosody": 0.5, "fraud": 1.0}
_LEVEL_ORDER: dict[str, int] = {"none": 0, "caution": 1, "high": 2}
_REASON_ORDER = ("fraud", "spoof", "speaker", "prosody")  # stable order: strongest story first
_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}

# --- thresholds (Settings.fire_threshold / fire_min_confidence override the first two)
FIRE_THRESHOLD = 0.5        # smoothed risk score needed for a signal to fire
FIRE_MIN_CONFIDENCE = 0.3   # smoothed confidence needed for a signal to fire
MIN_EVIDENCE = 0.3          # smoothed score * confidence needed to fire (blocks low-confidence blips)
HIGH_MIN_HARD_SIGNALS = 2   # independent hard signals needed for "high"
SPOOF_LIKELY_P = 0.8        # wording only: "likely" vs "possible" synthetic voice

DEFAULT_ACTIONS = {
    "spoof": "Audio shows signs of synthetic speech. Do not rely on voice recognition; use out-of-band verification.",
    "speaker": "Voice does not match the enrolled customer. Complete step-up verification before any change.",
    "prosody": "Caller sounds under pressure. Slow down and ask open questions.",
    "fraud": "Conversation matches a known fraud pattern. Slow down and verify before acting on any request.",
}
HIGH_ACTION = (
    "Do not process any money movement or account changes on this call. "
    "Verify by calling back on the number on file and escalate to the fraud team."
)


@dataclass
class SignalState:
    score: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    details: dict = field(default_factory=dict)
    seen: bool = False
    raw_score: float = 0.0       # latest unsmoothed reading
    raw_confidence: float = 0.0


@dataclass
class Evidence:
    """Strongest reading of a signal while it was firing (latched for the call)."""

    score: float
    confidence: float
    reason: str
    details: dict
    patterns: dict[str, dict] = field(default_factory=dict)   # fraud: pattern id -> pattern
    citations: dict[str, dict] = field(default_factory=dict)  # fraud: pattern id -> citation


def _pattern_rank(p: dict) -> int:
    return _SEVERITY_RANK.get(str(p.get("severity", "")).lower(), 0)


class Fusion:
    def __init__(self, fire_threshold: float = FIRE_THRESHOLD, fire_min_confidence: float = FIRE_MIN_CONFIDENCE,
                 attack: float = 0.7, release: float = 0.2, min_evidence: float = MIN_EVIDENCE):
        self.fire_threshold = fire_threshold
        self.fire_min_confidence = fire_min_confidence
        self.min_evidence = min_evidence
        self.attack = attack
        self.release = release
        self.reset()

    def reset(self) -> None:
        self.signals: dict[str, SignalState] = {k: SignalState() for k in WEIGHTS}
        self.evidence: dict[str, Evidence] = {}
        self.trust: float = 100.0
        self.level: AlertLevel = "none"
        self._emitted_level: AlertLevel | None = None
        self._emitted_signals: set[str] = set()
        self._emitted_patterns: set[str] = set()

    # ------------------------------------------------------------ updates

    def update(self, r: DetectorResult) -> None:
        st = self.signals.setdefault(r.signal, SignalState())
        a = EMA_ALPHA.get(r.signal, 0.6)
        if not st.seen or r.confidence == 0.0 or st.confidence == 0.0:
            st.score, st.confidence = r.score, r.confidence
        else:
            st.score = a * r.score + (1 - a) * st.score
            st.confidence = a * r.confidence + (1 - a) * st.confidence
        st.reason, st.details, st.seen = r.reason, r.details, True
        st.raw_score, st.raw_confidence = r.score, r.confidence
        if self._fires(st):
            self._latch(r.signal, st)

    def _fires(self, s: SignalState) -> bool:
        return (s.score >= self.fire_threshold and s.confidence >= self.fire_min_confidence
                and s.score * s.confidence >= self.min_evidence)

    def _latch(self, name: str, st: SignalState) -> None:
        ev = self.evidence.get(name)
        if ev is None or st.raw_score * st.raw_confidence >= ev.score * ev.confidence:
            prev = ev
            ev = Evidence(score=st.raw_score, confidence=st.raw_confidence, reason=st.reason, details=st.details)
            if prev is not None:
                ev.patterns, ev.citations = prev.patterns, prev.citations
            self.evidence[name] = ev
        if name == "fraud":
            for p in st.details.get("patterns", []) or []:
                pid = p.get("id")
                if pid and (pid not in ev.patterns or _pattern_rank(p) > _pattern_rank(ev.patterns[pid])):
                    ev.patterns[pid] = p
            for c in st.details.get("citations", []) or []:
                pid = c.get("pattern_id")
                if pid and pid not in ev.citations:
                    ev.citations[pid] = c

    def components(self) -> dict[str, float]:
        return {k: round(s.score * s.confidence * WEIGHTS.get(k, 0.5), 4) for k, s in self.signals.items()}

    def raw_trust(self) -> float:
        prod = 1.0
        for r in self.components().values():
            prod *= 1.0 - min(1.0, max(0.0, r))
        return 100.0 * prod

    def fired(self) -> list[str]:
        """Signals firing right now (smoothed values)."""
        return [k for k, s in self.signals.items() if self._fires(s)]

    def evidence_signals(self) -> list[str]:
        """Signals that have fired at any point in this call, in reason order."""
        order = [k for k in _REASON_ORDER if k in self.evidence]
        return order + [k for k in self.evidence if k not in order]

    def compute_level(self) -> AlertLevel:
        fired = set(self.fired()) | set(self.evidence)
        hard = [k for k in fired if k in HARD_SIGNALS]
        if len(hard) >= HIGH_MIN_HARD_SIGNALS:
            return "high"
        if fired:
            return "caution"
        return "none"

    def trust_event(self, utterance_id: int) -> TrustEvent:
        raw = self.raw_trust()
        alpha = self.attack if raw < self.trust else self.release
        self.trust = alpha * raw + (1 - alpha) * self.trust
        return TrustEvent(utterance_id=utterance_id, score=round(self.trust, 1), raw=round(raw, 1),
                          components=self.components())

    # ------------------------------------------------------------ alert

    def top_patterns(self) -> list[dict]:
        """Fraud patterns seen this call, highest severity first (stable for ties)."""
        ev = self.evidence.get("fraud")
        if ev is None:
            return []
        pats = list(ev.patterns.values())
        return sorted(pats, key=lambda p: -_pattern_rank(p))

    def _fraud_reasons(self) -> list[str]:
        ev = self.evidence["fraud"]
        pats = self.top_patterns()
        if not pats:
            return [f"Fraud analyzer: {ev.reason}" if ev.reason else f"Fraud risk {ev.score:.2f}"]
        top = pats[0]
        quote = str(top.get("quote", "")).strip()
        line = f'Fraud pattern "{top.get("name") or top.get("id")}"'
        if quote:
            line += f': "{quote}"'
        if top.get("utterance_id") is not None:
            line += f" (utterance {top['utterance_id']})"
        out = [line]
        if len(pats) > 1:
            out.append("Also matched: " + ", ".join(str(p.get("name") or p.get("id")) for p in pats[1:]))
        return out

    def _speaker_reason(self) -> str:
        ev = self.evidence["speaker"]
        sim = ev.details.get("similarity")
        if isinstance(sim, (int, float)):
            return f"Voice doesn't match enrolled customer (similarity {sim:.2f})"
        return f"Voice doesn't match enrolled customer (risk {ev.score:.2f})"

    def _spoof_reason(self) -> str:
        ev = self.evidence["spoof"]
        p = ev.score
        word = "likely" if p >= SPOOF_LIKELY_P else "possible"
        return f"Synthetic voice {word} (P={p:.2f})"

    def _voice_match_note(self) -> str | None:
        """Clone story: voice-ID passed, but the voice is synthetic."""
        sp = self.signals.get("speaker")
        if not sp or not sp.seen or sp.raw_confidence <= 0 or "speaker" in self.evidence:
            return None
        if sp.raw_score >= self.fire_threshold:
            return None
        sim = sp.details.get("similarity")
        num = f"similarity {sim:.2f}" if isinstance(sim, (int, float)) else f"risk {sp.raw_score:.2f}"
        return f"Voice matches enrolled customer ({num}), but voice ID alone is not proof of identity"

    def _reasons(self) -> list[str]:
        reasons: list[str] = []
        for k in self.evidence_signals():
            if k == "fraud":
                reasons += self._fraud_reasons()
            elif k == "spoof":
                reasons.append(self._spoof_reason())
                note = self._voice_match_note()
                if note:
                    reasons.append(note)
            elif k == "speaker":
                reasons.append(self._speaker_reason())
            elif k == "prosody":
                ev = self.evidence[k]
                reasons.append(f"Caller sounds under pressure (score {ev.score:.2f})")
            else:
                reasons.append(f"{k}: {self.evidence[k].reason}")
        return reasons

    def _fraud_action(self) -> str:
        pats = self.top_patterns()
        if pats and pats[0].get("suggested_agent_action"):
            return str(pats[0]["suggested_agent_action"])
        ev = self.evidence.get("fraud")
        return str(ev.details.get("suggested_action", "")) if ev else ""

    def alert_event(self) -> AlertEvent:
        new = self.compute_level()
        if _LEVEL_ORDER[new] > _LEVEL_ORDER[self.level]:
            self.level = new  # latch: never de-escalate within a call
        signals = self.evidence_signals()
        citations: list[Citation] = []
        action = ""
        if "fraud" in self.evidence:
            action = self._fraud_action()
            citations = [Citation(**c) for c in self.evidence["fraud"].citations.values()]
        if self.level == "high":
            action = HIGH_ACTION + (f" {action}" if action else "")
        elif not action:
            for k in signals:
                if k in DEFAULT_ACTIONS:
                    action = DEFAULT_ACTIONS[k]
                    break
        return AlertEvent(level=self.level, reasons=self._reasons(), suggested_action=action,
                          signals=signals, citations=citations)

    def alert_if_changed(self) -> AlertEvent | None:
        """The alert, but only on a material change (level change, or a new signal / new
        fraud pattern id at the same level); None otherwise."""
        ev = self.alert_event()
        sigs = set(ev.signals)
        pats = set(self.evidence["fraud"].patterns) if "fraud" in self.evidence else set()
        pats |= {c.pattern_id for c in ev.citations}
        if ev.level == self._emitted_level and sigs <= self._emitted_signals and pats <= self._emitted_patterns:
            return None
        if ev.level != self._emitted_level:
            self._emitted_signals, self._emitted_patterns = set(), set()
        self._emitted_level = ev.level
        self._emitted_signals |= sigs
        self._emitted_patterns |= pats
        return ev
