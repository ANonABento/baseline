"""Fusion: detector results -> Trust Score + alert level + reasons + suggested action.

- Each signal keeps a running risk (EMA for per-utterance audio signals; the fraud
  analyzer already looks at the whole rolling transcript, so its latest value is used).
- Effective risk per signal = score * confidence * weight. Signals are combined with a
  noisy-OR so independent evidence accumulates: risk = 1 - prod(1 - r_i).
- Trust Score = 100 * (1 - risk), smoothed with fast attack (drops quickly) / slow release.
- A signal "fires" when score >= fire_threshold and confidence >= fire_min_confidence.
  Alert: none (0 fired), caution (1 fired, or only the soft prosody signal), high (>= 2
  independent hard signals among speaker/spoof/fraud). The level latches for the call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from events import AlertEvent, AlertLevel, Citation, DetectorResult, TrustEvent

WEIGHTS: dict[str, float] = {"spoof": 0.9, "fraud": 0.85, "speaker": 0.7, "prosody": 0.3}
HARD_SIGNALS = ("speaker", "spoof", "fraud")
EMA_ALPHA: dict[str, float] = {"spoof": 0.6, "speaker": 0.6, "prosody": 0.5, "fraud": 1.0}
_LEVEL_ORDER: dict[str, int] = {"none": 0, "caution": 1, "high": 2}

DEFAULT_ACTIONS = {
    "spoof": "Audio shows signs of synthetic speech. Do not rely on voice recognition; use out-of-band verification.",
    "speaker": "Voice does not match the enrolled customer. Complete step-up verification before any change.",
    "prosody": "Caller sounds under pressure. Slow down and ask open questions.",
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


class Fusion:
    def __init__(self, fire_threshold: float = 0.5, fire_min_confidence: float = 0.3,
                 attack: float = 0.7, release: float = 0.2):
        self.fire_threshold = fire_threshold
        self.fire_min_confidence = fire_min_confidence
        self.attack = attack
        self.release = release
        self.reset()

    def reset(self) -> None:
        self.signals: dict[str, SignalState] = {k: SignalState() for k in WEIGHTS}
        self.trust: float = 100.0
        self.level: AlertLevel = "none"
        self._last_alert_key: tuple | None = None

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

    def components(self) -> dict[str, float]:
        return {k: round(s.score * s.confidence * WEIGHTS.get(k, 0.5), 4) for k, s in self.signals.items()}

    def raw_trust(self) -> float:
        prod = 1.0
        for r in self.components().values():
            prod *= 1.0 - min(1.0, max(0.0, r))
        return 100.0 * prod

    def fired(self) -> list[str]:
        return [
            k for k, s in self.signals.items()
            if s.score >= self.fire_threshold and s.confidence >= self.fire_min_confidence
        ]

    def compute_level(self) -> AlertLevel:
        fired = self.fired()
        hard = [k for k in fired if k in HARD_SIGNALS]
        if len(hard) >= 2:
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

    def alert_event(self) -> AlertEvent:
        new = self.compute_level()
        if _LEVEL_ORDER[new] > _LEVEL_ORDER[self.level]:
            self.level = new  # latch: never de-escalate within a call
        fired = self.fired()
        reasons = [f"{k}: {self.signals[k].reason}" for k in fired]
        citations: list[Citation] = []
        action = ""
        fraud = self.signals.get("fraud")
        if "fraud" in fired and fraud:
            action = fraud.details.get("suggested_action", "")
            citations = [Citation(**c) for c in fraud.details.get("citations", [])]
        if self.level == "high":
            action = HIGH_ACTION + (f" {action}" if action else "")
        elif not action:
            for k in fired:
                if k in DEFAULT_ACTIONS:
                    action = DEFAULT_ACTIONS[k]
                    break
        return AlertEvent(level=self.level, reasons=reasons, suggested_action=action,
                          signals=fired, citations=citations)

    def alert_if_changed(self) -> AlertEvent | None:
        ev = self.alert_event()
        key = (ev.level, tuple(ev.signals), tuple(c.pattern_id for c in ev.citations))
        if key == self._last_alert_key:
            return None
        self._last_alert_key = key
        return ev
