"""Synthetic-speech / voice-clone detection. Pick with SPOOF_PROVIDER=stub|pretrained|wavlm.

SpoofDetector            stub (confidence 0 unless a clip carries stub hints).
PretrainedSpoofDetector  mo-thecreator/Deepfake-audio-detection (wav2vec2 classifier, MPS)
                         on SPOOF_WINDOW_S windows (default 4 s, hop 2 s).
WavLMSpoofDetector       our classifier: frozen microsoft/wavlm-base-plus mean-pooled
                         embeddings -> logistic regression (models/spoof_lr.joblib, trained by
                         scripts/train_spoof.py); window/hop/layer come from the model file.

Both real detectors score every window of the utterance and aggregate per utterance:
score (risk) = mean P(fake) over windows; `details` carries the per-window values and max.
Confidence grows with utterance length (full at >= 2.5 s), capped at SPOOF_MAX_CONFIDENCE
because neither model is validated on modern voice clones yet; utterances shorter than
SPOOF_MIN_AUDIO_S return confidence 0.
"""

from __future__ import annotations

import logging

import numpy as np

from core import CallContext, Utterance
from detectors.base import Detector, stub_result
from events import DetectorResult
from settings import Settings

log = logging.getLogger(__name__)


class SpoofDetector(Detector):
    name = "spoof"

    async def analyze(self, utt: Utterance, ctx: CallContext) -> DetectorResult:
        return stub_result(self.name, ctx, "Spoof detector not loaded (stub).")


class _WindowedSpoofDetector(Detector):
    name = "spoof"
    FULL_CONF_S = 2.5
    label = "spoof model"

    def __init__(self, settings: Settings):
        self.s = settings

    # subclasses: window params + blocking per-window P(fake) on the spoof thread
    def _window_params(self) -> tuple[float, float]:
        return self.s.spoof_window_s, self.s.spoof_hop_s

    def _probs_sync(self, wins: list[np.ndarray]) -> np.ndarray:
        raise NotImplementedError

    def _load_sync(self) -> None:
        raise NotImplementedError

    def warmup(self) -> None:
        from ml import runtime
        from ml.spoof_models import EXECUTOR

        runtime.submit(EXECUTOR, self._load_sync).result()

    async def analyze(self, utt: Utterance, ctx: CallContext) -> DetectorResult:
        from ml import runtime
        from ml.audio import windows
        from ml.spoof_models import EXECUTOR

        win_s, hop_s = self._window_params()
        wins = windows(utt.audio, utt.sample_rate, win_s, hop_s, min_s=self.s.spoof_min_audio_s)
        if not wins:
            return DetectorResult(signal=self.name, score=0.0, confidence=0.0,
                                  reason=f"Utterance too short for spoof check ({utt.duration:.1f}s).",
                                  details={"short": True, "model": self.label})
        probs = await runtime.run(EXECUTOR, self._probs_sync, wins)
        p = float(np.mean(probs))
        conf = self.s.spoof_max_confidence * min(1.0, utt.duration / self.FULL_CONF_S)
        if p >= 0.8:
            reason = f"Synthetic-speech artifacts detected (P(fake) {p:.2f} over {len(wins)} window(s))."
        elif p >= 0.5:
            reason = f"Possible synthetic speech (P(fake) {p:.2f})."
        else:
            reason = f"No synthetic-speech artifacts (P(fake) {p:.2f})."
        return DetectorResult(
            signal=self.name, score=round(p, 3), confidence=round(conf, 3), reason=reason,
            details={"p_fake_windows": [round(float(x), 3) for x in probs], "p_fake_max": round(float(np.max(probs)), 3),
                     "window_s": win_s, "model": self.label},
        )


class PretrainedSpoofDetector(_WindowedSpoofDetector):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.label = settings.spoof_pretrained_model

    def _model(self):
        from ml.spoof_models import PretrainedSpoof

        return PretrainedSpoof.get(self.s.spoof_pretrained_model, self.s.spoof_device)

    def _load_sync(self) -> None:
        self._model().warmup()

    def _probs_sync(self, wins: list[np.ndarray]) -> np.ndarray:
        return self._model().fake_probs(wins)


class WavLMSpoofDetector(_WindowedSpoofDetector):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        if not settings.spoof_lr_path.is_file():
            raise FileNotFoundError(f"{settings.spoof_lr_path} missing; train it with scripts/train_spoof.py")
        self.label = f"wavlm-lr:{settings.spoof_lr_path.name}"
        self._win: tuple[float, float] | None = None

    def _lr(self):
        from ml.spoof_models import SpoofLR

        return SpoofLR.get(self.s.spoof_lr_path)

    def _wavlm(self):
        from ml.spoof_models import WavLMEmbedder

        return WavLMEmbedder.get(self._lr().wavlm_model, self.s.spoof_device, self.s.wavlm_safetensors_revision)

    def _window_params(self) -> tuple[float, float]:
        if self._win is None:  # bundle load is cheap (sklearn only); first call may come from the loop
            lr = self._lr()
            self._win = (lr.window_s, lr.hop_s)
        return self._win

    def _load_sync(self) -> None:
        self._window_params()
        self._wavlm().warmup()

    def _probs_sync(self, wins: list[np.ndarray]) -> np.ndarray:
        lr = self._lr()
        return lr.fake_probs(self._wavlm().embed(wins, layer=lr.layer))


def make_spoof_detector(settings: Settings) -> Detector:
    from ml.runtime import has_modules

    p = settings.spoof_provider
    if p == "pretrained":
        if has_modules("transformers", "torch"):
            return PretrainedSpoofDetector(settings)
        log.warning("SPOOF_PROVIDER=pretrained but transformers/torch are not installed; using stub")
    elif p == "wavlm":
        if has_modules("transformers", "torch", "sklearn", "joblib"):
            try:
                return WavLMSpoofDetector(settings)
            except FileNotFoundError as e:
                log.warning("SPOOF_PROVIDER=wavlm: %s; using stub", e)
        else:
            log.warning("SPOOF_PROVIDER=wavlm but ML deps are not installed; using stub")
    return SpoofDetector()
