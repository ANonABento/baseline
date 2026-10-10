"""Speaker verification vs. the customer's enrolled voiceprint.

STUB. Drop-in plan: SpeechBrain ECAPA-TDNN embeddings, cosine similarity against the
enrolled embedding in data/enroll/<customer_id>.npy, risk = 1 - calibrated similarity."""

from __future__ import annotations

from core import CallContext, Utterance
from detectors.base import Detector, stub_result
from events import DetectorResult


class SpeakerDetector(Detector):
    name = "speaker"

    async def analyze(self, utt: Utterance, ctx: CallContext) -> DetectorResult:
        return stub_result(self.name, ctx, "Speaker verification not loaded (stub).")
