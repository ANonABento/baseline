"""Shared data types passed between the pipeline, providers and detectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class Utterance:
    """One VAD segment. `audio` is float32 mono in [-1, 1] at `sample_rate`."""

    id: int
    audio: np.ndarray
    sample_rate: int
    t_start: float  # seconds since call start
    t_end: float
    text: str = ""  # filled in by STT

    @property
    def duration(self) -> float:
        return len(self.audio) / self.sample_rate


@dataclass
class CallContext:
    """Per-call state shared by detectors (rolling transcript, caller baselines, ...)."""

    customer_id: str = ""
    utterances: list[Utterance] = field(default_factory=list)
    # Free-form per-detector state, e.g. prosody baseline stats. Key by detector name.
    state: dict[str, Any] = field(default_factory=dict)
    # Stub-only hints loaded from `<clip>.meta.json` (see backend/README.md). Real detectors ignore.
    stub_hints: dict[str, Any] = field(default_factory=dict)

    @property
    def transcript(self) -> str:
        return " ".join(u.text for u in self.utterances if u.text).strip()
