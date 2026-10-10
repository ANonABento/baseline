"""Pressure / arousal relative to the caller's OWN baseline (soft signal, never "lie detection").

Placeholder implementation: loudness (RMS dBFS) and zero-crossing rate per utterance,
baseline = utterances that start in the first `baseline_s` seconds, risk = how far the
current utterance deviates (z-score). Drop-in plan: parselmouth pitch + speech rate."""

from __future__ import annotations

import numpy as np

from core import CallContext, Utterance
from detectors.base import Detector
from events import DetectorResult


def features(audio: np.ndarray) -> dict[str, float]:
    if audio.size == 0:
        return {"rms_db": -120.0, "zcr": 0.0}
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    zcr = float(np.mean(np.abs(np.diff(np.signbit(audio).astype(np.int8))))) if audio.size > 1 else 0.0
    return {"rms_db": 20.0 * np.log10(max(rms, 1e-6)), "zcr": zcr}


class ProsodyDetector(Detector):
    name = "prosody"

    def __init__(self, baseline_s: float = 20.0, min_baseline_utts: int = 2):
        self.baseline_s = baseline_s
        self.min_baseline_utts = min_baseline_utts

    async def analyze(self, utt: Utterance, ctx: CallContext) -> DetectorResult:
        hint = ctx.stub_hints.get(self.name)
        if hint is not None:
            from detectors.base import stub_result

            return stub_result(self.name, ctx, "")
        st = ctx.state.setdefault(self.name, {"baseline": []})
        f = features(utt.audio)
        base: list[dict[str, float]] = st["baseline"]
        if utt.t_start < self.baseline_s or len(base) < self.min_baseline_utts:
            base.append(f)
            return DetectorResult(
                signal=self.name, score=0.0, confidence=0.0,
                reason=f"Building caller baseline ({len(base)} utterance(s)).",
                details={"features": f, "baseline": True},
            )
        z = {}
        for k, floor in (("rms_db", 2.0), ("zcr", 0.01)):
            vals = np.array([b[k] for b in base])
            z[k] = abs(f[k] - float(vals.mean())) / max(float(vals.std()), floor)
        zmax = max(z.values())
        score = float(np.clip((zmax - 1.0) / 3.0, 0.0, 1.0))
        reason = (
            "Speech energy/rate close to this caller's baseline."
            if score < 0.3
            else f"Delivery deviates from caller baseline (z={zmax:.1f}); possible pressure."
        )
        return DetectorResult(
            signal=self.name, score=round(score, 3), confidence=0.25, reason=reason,
            details={"features": f, "z": {k: round(v, 2) for k, v in z.items()}},
        )
