"""Streaming utterance segmentation (VAD).

`Segmenter` is the interface. `FrameVAD` implements the streaming state machine on fixed
frames; `EnergyVAD` (dependency-free placeholder) and `SileroVAD` (silero-vad, `ml` extra)
only decide per frame whether it is speech. `make_segmenter(settings)` picks one (VAD_PROVIDER)."""

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


class FrameVAD(Segmenter):
    """Streaming frame-based segmenter. Subclasses decide per frame whether it is speech
    (`_is_speech`); this class does buffering, pre-roll, min-speech, hangover and max-length.
    Timestamps are seconds since the last reset()."""

    def __init__(self, sample_rate: int = 16_000, frame_samples: int = 480, min_speech_ms: int = 250,
                 hangover_ms: int = 500, max_utterance_ms: int = 15_000, preroll_ms: int = 150):
        self.sr = sample_rate
        self.frame = frame_samples
        frame_ms = 1000.0 * frame_samples / sample_rate
        self.min_speech_frames = max(1, int(min_speech_ms / frame_ms))
        self.hangover_frames = max(1, int(hangover_ms / frame_ms))
        self.max_frames = max(1, int(max_utterance_ms / frame_ms))
        self.preroll_frames = int(preroll_ms / frame_ms)
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

    @abstractmethod
    def _is_speech(self, frame: np.ndarray) -> bool:
        ...

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


class EnergyVAD(FrameVAD):
    """Dependency-free placeholder: a 30 ms frame is speech when its RMS exceeds threshold_db."""

    def __init__(self, sample_rate: int = 16_000, threshold_db: float = -40.0, frame_ms: int = 30,
                 min_speech_ms: int = 250, hangover_ms: int = 500, max_utterance_ms: int = 15_000,
                 preroll_ms: int = 150):
        self.threshold_db = threshold_db
        super().__init__(sample_rate, int(sample_rate * frame_ms / 1000), min_speech_ms, hangover_ms,
                         max_utterance_ms, preroll_ms)

    def _is_speech(self, frame: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))
        return 20.0 * np.log10(max(rms, 1e-9)) > self.threshold_db


class SileroVAD(FrameVAD):
    """silero-vad 6 streaming: one model call per 512-sample (32 ms) chunk at 16 kHz, with
    hysteresis (start at `threshold`, keep going until prob < threshold - 0.15), the same
    rule silero's own VADIterator uses. ~0.15 ms per chunk on CPU, so it runs inline on the
    event loop. The model is stateful (RNN), so every segmenter owns its own instance."""

    CHUNK = 512

    def __init__(self, sample_rate: int = 16_000, threshold: float = 0.5, min_speech_ms: int = 250,
                 hangover_ms: int = 500, max_utterance_ms: int = 15_000, preroll_ms: int = 150):
        if sample_rate != 16_000:
            raise ValueError("SileroVAD is configured for 16 kHz input (512-sample chunks)")
        import silero_vad
        import torch

        self._torch = torch
        self.model = silero_vad.load_silero_vad()
        self.threshold = threshold
        self.neg_threshold = max(threshold - 0.15, 0.01)
        self.last_prob = 0.0
        super().__init__(sample_rate, self.CHUNK, min_speech_ms, hangover_ms, max_utterance_ms, preroll_ms)

    def reset(self) -> None:
        super().reset()
        if hasattr(self, "model"):
            self.model.reset_states()

    def _is_speech(self, frame: np.ndarray) -> bool:
        with self._torch.inference_mode():
            self.last_prob = float(self.model(self._torch.from_numpy(np.ascontiguousarray(frame)), self.sr).item())
        return self.last_prob >= (self.neg_threshold if self._in_speech else self.threshold)


def make_segmenter(settings) -> Segmenter:
    """VAD_PROVIDER=energy|silero. silero falls back to energy if silero-vad is not installed."""
    s = settings
    if s.vad_provider == "silero":
        try:
            return SileroVAD(sample_rate=s.sample_rate, threshold=s.silero_threshold, min_speech_ms=s.vad_min_speech_ms,
                             hangover_ms=s.vad_hangover_ms, max_utterance_ms=s.vad_max_utterance_ms,
                             preroll_ms=s.vad_preroll_ms)
        except ImportError:
            import logging

            logging.getLogger(__name__).warning("VAD_PROVIDER=silero but silero-vad is not installed; using energy VAD")
    return EnergyVAD(sample_rate=s.sample_rate, threshold_db=s.vad_threshold_db, min_speech_ms=s.vad_min_speech_ms,
                     hangover_ms=s.vad_hangover_ms, max_utterance_ms=s.vad_max_utterance_ms, preroll_ms=s.vad_preroll_ms)
