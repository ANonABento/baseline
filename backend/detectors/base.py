"""Detector interface. Every detector returns a `DetectorResult`
`{signal, score (risk 0-1), confidence 0-1, reason, details}`.

Audio detectors (`requires_text = False`) run concurrently with STT as soon as an
utterance is segmented; text detectors run after STT for that utterance finishes.
Blocking model inference must go through `asyncio.to_thread`."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core import CallContext, Utterance
from events import DetectorResult, SignalName


class Detector(ABC):
    name: SignalName
    requires_text: bool = False

    @abstractmethod
    async def analyze(self, utt: Utterance, ctx: CallContext) -> DetectorResult:
        ...

    def reset(self, ctx: CallContext) -> None:  # noqa: B027 - optional hook
        """Called at the start of each call."""


def stub_result(name: SignalName, ctx: CallContext, default_reason: str) -> DetectorResult:
    """Neutral stub output (confidence 0 => ignored by fusion), unless the replayed clip
    has a `<clip>.meta.json` sidecar with `stub_hints` for this signal (demo/dev only)."""
    hint = ctx.stub_hints.get(name)
    if isinstance(hint, (int, float)):
        hint = {"score": float(hint)}
    if isinstance(hint, dict) and "score" in hint:
        return DetectorResult(
            signal=name,
            score=max(0.0, min(1.0, float(hint["score"]))),
            confidence=max(0.0, min(1.0, float(hint.get("confidence", 0.8)))),
            reason=str(hint.get("reason", f"[stub hint] {name} score from clip metadata")),
            details={"stub": True, "from_hint": True},
        )
    return DetectorResult(signal=name, score=0.0, confidence=0.0, reason=default_reason, details={"stub": True})
