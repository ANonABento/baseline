"""Streaming utterance segmentation (VAD).

`Segmenter` is the interface; `EnergyVAD` is a dependency-free placeholder that silero-vad
can replace (implement `feed`/`flush` with the same semantics)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class Segment:
    audio: np.ndarray  # float32 mono
    t_start: float
    t_end: float


class Segmenter(ABC):
    @abstractmethod
    def feed(self, samples: np.ndarray) -> list[Segment]:
        """Push float32 mono samples; return any utterances that just finished."""

    @abstractmethod
    def flush(self) -> list[Segment]:
        """End of stream: return the in-progress utterance if long enough."""

    @abstractmethod
    def reset(self) -> None:
        ...


class EnergyVAD(Segmenter):
    def __init__(self, sample_rate: int = 16_000, threshold_db: float = -40.0, frame_ms: int = 30,
                 min_speech_ms: int = 250, hangover_ms: int = 500, max_utterance_ms: int = 15_000,
                 preroll_ms: int = 150):
        self.sr = sample_rate
        self.threshold_db = threshold_db
        self.frame = int(sample_rate * frame_ms / 1000)
        self.min_speech_frames = max(1, min_speech_ms // frame_ms)
        self.hangover_frames = max(1, hangover_ms // frame_ms)
        self.max_frames = max(1, max_utterance_ms // frame_ms)
        self.preroll_frames = preroll_ms // frame_ms
        self.reset()

    def reset(self) -> None:
        self._pending = np.zeros(0, dtype=np.float32)  # samples not yet framed
        self._frame_idx = 0  # index of next frame (for timestamps)
        self._preroll: list[np.ndarray] = []
        self._cur: list[np.ndarray] = []
        self._cur_start_frame = 0
        self._speech_frames = 0
        self._silence_run = 0
        self._in_speech = False

    def _is_speech(self, frame: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))
        return 20.0 * np.log10(max(rms, 1e-9)) > self.threshold_db

    def _close(self) -> Segment | None:
        seg = None
        if self._speech_frames >= self.min_speech_frames:
            # trim the trailing silence (keep a little tail)
            keep = len(self._cur) - max(0, self._silence_run - 3)
            frames = self._cur[:keep]
            audio = np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)
            t0 = self._cur_start_frame * self.frame / self.sr
            seg = Segment(audio=audio, t_start=t0, t_end=t0 + len(audio) / self.sr)
        self._cur, self._speech_frames, self._silence_run, self._in_speech = [], 0, 0, False
        return seg

    def feed(self, samples: np.ndarray) -> list[Segment]:
        out: list[Segment] = []
        buf = np.concatenate([self._pending, samples.astype(np.float32, copy=False)])
        n = len(buf) // self.frame
        for i in range(n):
            f = buf[i * self.frame:(i + 1) * self.frame]
            speech = self._is_speech(f)
            if not self._in_speech:
                if speech:
                    self._in_speech = True
                    self._cur = list(self._preroll) + [f]
                    self._cur_start_frame = self._frame_idx - len(self._preroll)
                    self._speech_frames, self._silence_run = 1, 0
                    self._preroll = []
                else:
                    self._preroll.append(f)
                    if len(self._preroll) > self.preroll_frames:
                        self._preroll.pop(0)
            else:
                self._cur.append(f)
                if speech:
                    self._speech_frames += 1
                    self._silence_run = 0
                else:
                    self._silence_run += 1
                if self._silence_run >= self.hangover_frames or len(self._cur) >= self.max_frames:
                    seg = self._close()
                    if seg is not None:
                        out.append(seg)
            self._frame_idx += 1
        self._pending = buf[n * self.frame:].copy()
        return out

    def flush(self) -> list[Segment]:
        seg = self._close() if self._in_speech else None
        self._preroll, self._pending = [], np.zeros(0, dtype=np.float32)
        return [seg] if seg is not None else []
