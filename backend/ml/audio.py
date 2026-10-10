"""Numpy-only audio helpers shared by detectors and scripts (no torch import)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf


def resample(audio: np.ndarray, sr: int, target_sr: int) -> np.ndarray:
    """Polyphase resampling when scipy is available (ml extra), linear interpolation otherwise."""
    if sr == target_sr or not len(audio):
        return audio.astype(np.float32, copy=False)
    try:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(int(sr), int(target_sr))
        return resample_poly(audio, target_sr // g, sr // g).astype(np.float32)
    except ImportError:
        n_out = int(round(len(audio) * target_sr / sr))
        return np.interp(np.linspace(0, len(audio) - 1, n_out), np.arange(len(audio)), audio).astype(np.float32)


def read_audio(path: Path | str, target_sr: int = 16_000) -> np.ndarray:
    """Any soundfile-readable file -> float32 mono at target_sr. (torchaudio.load needs
    torchcodec in this torch version, so we never use it.)"""
    audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return resample(audio.mean(axis=1), sr, target_sr)


def windows(audio: np.ndarray, sr: int, win_s: float, hop_s: float, min_s: float = 0.0) -> list[np.ndarray]:
    """Equal-length analysis windows covering the whole signal (so they can be batched).

    Shorter-than-window audio is returned as one window if it is at least `min_s` long.
    The last window is aligned to the end of the signal so no tail is skipped."""
    n, win, hop = len(audio), int(win_s * sr), max(1, int(hop_s * sr))
    if n < max(1, int(min_s * sr)):
        return []
    if n <= win:
        return [audio]
    starts = list(range(0, n - win + 1, hop))
    if starts[-1] + win < n:
        starts.append(n - win)
    return [audio[s:s + win] for s in starts]
