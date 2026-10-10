"""mlx-whisper STT on the Apple GPU (default mlx-community/whisper-large-v3-turbo).

Inference runs on the dedicated `stt` thread (ml.runtime) so the event loop keeps streaming."""

from __future__ import annotations

import logging

import numpy as np

from core import Utterance
from ml import runtime
from ml.whisper import EXECUTOR, MlxWhisper, WhisperResult
from providers.base import STTProvider

log = logging.getLogger(__name__)


class MlxWhisperSTT(STTProvider):
    name = "mlx"

    def __init__(self, model: str = "mlx-community/whisper-large-v3-turbo", language: str = "en",
                 min_audio_s: float = 0.3):
        self.model = model
        self.language = language
        self.min_audio_s = min_audio_s

    def _model(self) -> MlxWhisper:
        return MlxWhisper.get(self.model, self.language)

    def _transcribe_sync(self, audio: np.ndarray) -> WhisperResult:
        return self._model().transcribe(audio)

    async def transcribe(self, utt: Utterance) -> str:
        if utt.duration < self.min_audio_s:
            return ""
        r = await runtime.run(EXECUTOR, self._transcribe_sync, utt.audio)
        if r.dropped_segments:
            log.debug("utt %s: dropped %d likely-hallucinated segment(s)", utt.id, r.dropped_segments)
        return r.text

    def warmup(self) -> None:
        """Blocking: load + one dummy inference on the stt thread."""
        runtime.submit(EXECUTOR, lambda: self._model().warmup()).result()
