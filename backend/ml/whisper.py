"""mlx-whisper wrapper (Apple GPU). Use only via the `stt` executor (ml.runtime.run)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from ml import runtime

log = logging.getLogger(__name__)
EXECUTOR = "stt"

# Whisper hallucinates on near-silence ("Thank you." etc). Drop segments that look like that.
NO_SPEECH_PROB = 0.6
LOW_LOGPROB = -1.0
MAX_COMPRESSION = 2.4


@dataclass
class WhisperResult:
    text: str
    dropped_segments: int = 0


class MlxWhisper:
    def __init__(self, repo: str, language: str = "en"):
        self.repo = repo
        self.language = language

    @classmethod
    def get(cls, repo: str, language: str = "en") -> "MlxWhisper":
        return runtime.cached(("whisper", repo, language), lambda: cls(repo, language))

    def transcribe(self, audio: np.ndarray) -> WhisperResult:
        import mlx_whisper

        r = mlx_whisper.transcribe(
            audio.astype(np.float32, copy=False),
            path_or_hf_repo=self.repo,
            language=self.language,
            condition_on_previous_text=False,  # each utterance stands alone; avoids repetition loops
            verbose=None,
        )
        kept, dropped = [], 0
        for seg in r.get("segments", []):
            silent = seg.get("no_speech_prob", 0.0) > NO_SPEECH_PROB and seg.get("avg_logprob", 0.0) < LOW_LOGPROB
            if silent or seg.get("compression_ratio", 0.0) > MAX_COMPRESSION:
                dropped += 1
                continue
            kept.append(seg.get("text", "").strip())
        text = " ".join(t for t in kept if t) if r.get("segments") else (r.get("text") or "").strip()
        return WhisperResult(text=text.strip(), dropped_segments=dropped)

    def warmup(self) -> None:
        rng = np.random.default_rng(0)
        self.transcribe((0.01 * rng.standard_normal(16_000)).astype(np.float32))
