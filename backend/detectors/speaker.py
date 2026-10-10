"""Speaker verification vs. the customer's enrolled voiceprint.

SpeakerDetector       stub (confidence 0 unless a clip carries stub hints).
EcapaSpeakerDetector  SpeechBrain ECAPA-TDNN (CPU). Per utterance: embedding -> cosine
                      similarity with data/enroll/<customer_id>.npy (scripts/enroll.py) ->
                      calibrated risk. Pick with SPEAKER_PROVIDER=stub|ecapa.

Risk mapping (settings SPEAKER_ACCEPT_SIM / SPEAKER_REJECT_SIM): a logistic curve through
the midpoint of the two anchors, steep enough that sim == accept -> risk 0.10 and
sim == reject -> risk 0.90. Confidence grows with utterance length (full at >= 3 s) and is
capped at SPEAKER_MAX_CONFIDENCE; utterances shorter than SPEAKER_MIN_AUDIO_S, or calls
without an enrolled profile, return confidence 0 (no opinion, ignored by fusion).
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from core import CallContext, Utterance
from detectors.base import Detector, stub_result
from events import DetectorResult
from settings import Settings

log = logging.getLogger(__name__)


class SpeakerDetector(Detector):
    name = "speaker"

    async def analyze(self, utt: Utterance, ctx: CallContext) -> DetectorResult:
        return stub_result(self.name, ctx, "Speaker verification not loaded (stub).")


def similarity_to_risk(sim: float, accept: float, reject: float) -> float:
    """Logistic through mid=(accept+reject)/2 with risk(accept)=0.1, risk(reject)=0.9."""
    if accept <= reject:
        raise ValueError("speaker_accept_sim must be > speaker_reject_sim")
    mid = (accept + reject) / 2.0
    scale = (accept - mid) / math.log(9.0)
    return 1.0 / (1.0 + math.exp((sim - mid) / scale))


class EcapaSpeakerDetector(Detector):
    name = "speaker"
    FULL_CONF_S = 3.0

    def __init__(self, settings: Settings):
        self.s = settings
        self._profiles: dict[str, tuple[float, object]] = {}  # customer_id -> (mtime, Voiceprint|None)

    def _encoder(self):
        from ml.ecapa import EcapaEncoder

        return EcapaEncoder.get(self.s.speaker_model, self.s.pretrained_dir, self.s.speaker_device)

    def _embed(self, audio):
        return self._encoder().embed(audio)

    def warmup(self) -> None:
        from ml import runtime
        from ml.ecapa import EXECUTOR

        runtime.submit(EXECUTOR, lambda: self._encoder().warmup()).result()

    def profile(self, customer_id: str):
        """Enrolled voiceprint for this customer (re-read when the file changes)."""
        from ml import voiceprints

        try:
            npy, _ = voiceprints.paths(Path(self.s.enroll_dir), customer_id)
        except ValueError:
            return None
        mtime = npy.stat().st_mtime if npy.is_file() else -1.0
        cached = self._profiles.get(customer_id)
        if cached is None or cached[0] != mtime:
            cached = (mtime, voiceprints.load(Path(self.s.enroll_dir), customer_id))
            self._profiles[customer_id] = cached
        return cached[1]

    async def analyze(self, utt: Utterance, ctx: CallContext) -> DetectorResult:
        from ml import runtime
        from ml.ecapa import EXECUTOR, cosine

        vp = self.profile(ctx.customer_id)
        if vp is None:
            return DetectorResult(signal=self.name, score=0.0, confidence=0.0,
                                  reason=f"No voiceprint enrolled for {ctx.customer_id or 'this caller'}.",
                                  details={"enrolled": False, "customer_id": ctx.customer_id})
        if utt.duration < self.s.speaker_min_audio_s:
            return DetectorResult(signal=self.name, score=0.0, confidence=0.0,
                                  reason=f"Utterance too short for voice match ({utt.duration:.1f}s).",
                                  details={"enrolled": True, "customer_id": ctx.customer_id, "short": True})
        emb = await runtime.run(EXECUTOR, self._embed, utt.audio)
        sim = cosine(emb, vp.embedding)
        acc, rej = self.s.speaker_accept_sim, self.s.speaker_reject_sim
        risk = similarity_to_risk(sim, acc, rej)
        conf = self.s.speaker_max_confidence * min(1.0, utt.duration / self.FULL_CONF_S)

        st = ctx.state.setdefault(self.name, {"sims": []})
        st["sims"].append((sim, utt.duration))
        tot = sum(d for _, d in st["sims"])
        call_sim = sum(s * d for s, d in st["sims"]) / tot if tot else sim

        who = vp.name or ctx.customer_id
        if sim >= acc:
            reason = f"Voice matches enrolled voiceprint for {who} (similarity {sim:.2f})."
        elif sim <= rej:
            reason = f"Voice does NOT match enrolled voiceprint for {who} (similarity {sim:.2f})."
        else:
            reason = f"Voice match inconclusive for {who} (similarity {sim:.2f})."
        return DetectorResult(
            signal=self.name, score=round(risk, 3), confidence=round(conf, 3), reason=reason,
            details={"similarity": round(sim, 3), "call_similarity": round(call_sim, 3),
                     "accept_sim": acc, "reject_sim": rej, "customer_id": ctx.customer_id,
                     "enrolled": True, "model": self.s.speaker_model},
        )


def make_speaker_detector(settings: Settings) -> Detector:
    if settings.speaker_provider == "ecapa":
        from ml.runtime import has_modules

        if has_modules("speechbrain", "torch"):
            return EcapaSpeakerDetector(settings)
        log.warning("SPEAKER_PROVIDER=ecapa but speechbrain/torch are not installed; using stub")
    return SpeakerDetector()
