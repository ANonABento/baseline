"""Event schema: everything the server pushes to the dashboard over `WS /ws/call`.

All events are JSON objects with a `type` discriminator:

transcript  One finished utterance.
            {type, utterance_id, t_start, t_end, text, latency_ms?}
            `latency_ms` (optional, added with the real models) = STT time for this utterance.
            `speaker` ("ai"|"visitor") and `analyzed` (bool) are optional, set only on the live
            call stream (WS /ws/session/{id}); see backend/README.md "Live call API".
signal      One detector result for one utterance.
            {type, utterance_id, signal, score, confidence, reason, details, latency_ms}
            `signal` is one of speaker | spoof | prosody | fraud.
            `score` is RISK in [0, 1] (higher = more suspicious), `confidence` in [0, 1].
trust       Fused Trust Score after each utterance.
            {type, utterance_id, score (0-100, smoothed), raw (0-100, unsmoothed), components}
alert       Emitted when the alert level or its reasons change.
            {type, level (none|caution|high), reasons[], suggested_action, signals[], citations[]}
status      Session lifecycle / errors.
            {type, state, message, clip?}

Client -> server control messages (JSON text frames; binary frames are 16 kHz mono int16 PCM):
  {"type": "replay", "clip": "takeover.wav", "customer_id"?: "CUST-004217"}
                                                stream a clip from data/demo/ at real-time pace
  {"type": "start", "source": "mic", "customer_id"?: "..."}   start a fresh live call
  {"type": "customer", "customer_id": "CUST-004217"}
                                                select the customer on the call (whose enrolled
                                                voiceprint speaker verification uses); applies to
                                                the current call and later ones in this session
  {"type": "stop"}                              stop replay / end the call (flushes the last utterance)
  {"type": "reset"}                             start a fresh call (clears transcript + fusion state)
  {"type": "ping"}
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SignalName = Literal["speaker", "spoof", "prosody", "fraud"]
AlertLevel = Literal["none", "caution", "high"]


class DetectorResult(BaseModel):
    """Common detector output. `score` is risk (0 = looks legit, 1 = looks fraudulent)."""

    signal: SignalName
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


class TranscriptEvent(BaseModel):
    type: Literal["transcript"] = "transcript"
    utterance_id: int
    t_start: float
    t_end: float
    text: str
    latency_ms: float | None = None  # optional: STT latency for this utterance
    # optional, live calls only (WS /ws/session): who spoke and whether the line went through
    # Baseline's analysis pipeline. Absent/None on the classic /ws/call stream.
    speaker: Literal["ai", "visitor"] | None = None
    analyzed: bool | None = None


class SignalEvent(DetectorResult):
    type: Literal["signal"] = "signal"
    utterance_id: int
    latency_ms: float = 0.0


class TrustEvent(BaseModel):
    type: Literal["trust"] = "trust"
    utterance_id: int
    score: float
    raw: float
    components: dict[str, float] = Field(default_factory=dict)


class Citation(BaseModel):
    pattern_id: str
    name: str
    source: str


class AlertEvent(BaseModel):
    type: Literal["alert"] = "alert"
    level: AlertLevel
    reasons: list[str] = Field(default_factory=list)
    suggested_action: str = ""
    signals: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    state: str
    message: str = ""
    clip: str | None = None


Event = TranscriptEvent | SignalEvent | TrustEvent | AlertEvent | StatusEvent
