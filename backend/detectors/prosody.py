"""Delivery change relative to the caller's OWN earlier speech (soft signal, never "lie detection").

Thin pipeline adapter over `detectors/voice_state.py` (pitch, loudness, rate proxy, pauses
vs the speaker's own baseline, sustained-change rule, `insufficient_evidence` on poor audio).
`score` keeps its fusion meaning (0-1, soft, weight 0.3); the hedged observations live in
`details` (`stress_related_change`, `delivery_markers`, `status`, `calibration_status`)."""

from __future__ import annotations

import asyncio

from core import CallContext, Utterance
from detectors import voice_state
from detectors.base import Detector, stub_result
from events import DetectorResult


class ProsodyDetector(Detector):
    name = "prosody"

    def __init__(self, min_baseline_utts: int | None = None):
        self.min_baseline_utts = min_baseline_utts or voice_state.MIN_BASELINE_UTTS

    async def analyze(self, utt: Utterance, ctx: CallContext) -> DetectorResult:
        if ctx.stub_hints.get(self.name) is not None:
            return stub_result(self.name, ctx, "")
        base = ctx.state.setdefault(self.name, voice_state.SpeakerBaseline(min_n=self.min_baseline_utts))
        try:  # pitch tracking is blocking: keep it off the event loop; never raise into the pipeline
            f = await asyncio.to_thread(voice_state.extract_features, utt.audio, utt.sample_rate)
        except Exception:  # noqa: BLE001
            f = None
        d = voice_state.assess(f, base)
        status, change = d["status"], d["stress_related_change"]
        if status == "building_baseline":
            reason = f"Building this caller's baseline ({d['baseline_n']} of {base.min_n} utterances)."
        elif status == "insufficient_evidence":
            reason = f"Not enough usable audio to compare delivery ({', '.join(d['quality_problems'])})."
        elif d["delivery_markers"]:
            reason = ("Delivery differs from this caller's earlier speech: " + "; ".join(d["delivery_markers"][:3])
                      + ". This can have many causes, including a noisy line or a new topic.")
        else:
            reason = "Delivery close to this caller's earlier speech."
        return DetectorResult(
            signal=self.name, score=round(change or 0.0, 3), confidence=0.25 if status == "ok" else 0.0,
            reason=reason, details=d,
        )
