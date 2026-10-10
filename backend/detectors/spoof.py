"""Synthetic-speech / voice-clone detection.

STUB. Drop-in plan (master plan section 3): frozen WavLM/wav2vec2 embeddings on ~3 s
windows -> calibrated logistic regression; pretrained HF deepfake classifier as baseline."""

from __future__ import annotations

from core import CallContext, Utterance
from detectors.base import Detector, stub_result
from events import DetectorResult


class SpoofDetector(Detector):
    name = "spoof"

    async def analyze(self, utt: Utterance, ctx: CallContext) -> DetectorResult:
        return stub_result(self.name, ctx, "Spoof detector not loaded (stub).")
