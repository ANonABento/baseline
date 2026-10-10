"""Call audio recording: AI caller on the left channel, visitor mic (opt-in) on the right.

Chunks are kept with their offset (seconds since call start, same origin as transcript t_start)
and mixed into one stereo 16-bit WAV at the end of the call.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

MIC_RESYNC_S = 0.25  # mic chunks within this of the previous chunk's end are placed contiguously


class CallRecorder:
    def __init__(self, sample_rate: int, record_visitor: bool):
        self.sr = sample_rate
        self.record_visitor = record_visitor
        self.ai: list[tuple[float, np.ndarray]] = []
        self.mic: list[tuple[float, np.ndarray]] = []
        self._mic_end: float | None = None

    def add_ai(self, offset_s: float, audio: np.ndarray) -> None:
        if audio.size:
            self.ai.append((max(0.0, offset_s), np.asarray(audio, dtype=np.float32)))

    def add_mic(self, arrival_s: float, audio: np.ndarray) -> None:
        """arrival_s = when the chunk arrived (its end). Consecutive chunks are laid end to end;
        after a gap (or drift past MIC_RESYNC_S) the chunk is re-anchored to its arrival time."""
        if not self.record_visitor or not audio.size:
            return
        dur = len(audio) / self.sr
        start = max(0.0, arrival_s - dur)
        if self._mic_end is not None and abs(start - self._mic_end) <= MIC_RESYNC_S:
            start = self._mic_end
        self.mic.append((start, np.asarray(audio, dtype=np.float32)))
        self._mic_end = start + dur

    @property
    def has_audio(self) -> bool:
        return bool(self.ai or self.mic)

    def _track(self, chunks: list[tuple[float, np.ndarray]], n: int) -> np.ndarray:
        out = np.zeros(n, dtype=np.float32)
        for off, x in chunks:
            i = int(round(off * self.sr))
            if i >= n:
                continue
            seg = x[: n - i]
            out[i:i + len(seg)] += seg
        return out

    def write_wav(self, path: Path, duration_s: float) -> float:
        """Write the stereo WAV; returns its duration in seconds."""
        ends = [off + len(x) / self.sr for off, x in self.ai + self.mic]
        total = max([duration_s, *ends])
        n = int(np.ceil(total * self.sr))
        left = self._track(self.ai, n)
        right = self._track(self.mic, n)
        pcm = (np.clip(np.stack([left, right], axis=1), -1.0, 1.0) * 32767).astype("<i2")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".wav.tmp")
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(self.sr)
            w.writeframes(pcm.tobytes())
        tmp.replace(path)
        return round(n / self.sr, 2)
