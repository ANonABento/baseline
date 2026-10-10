"""Stub STT providers (no models).

`StubSTT` returns a placeholder. `SidecarTranscriptSTT` reads a transcript file that sits
next to a WAV (`data/demo/takeover.wav` -> `data/demo/takeover.txt`) so the fraud analyzer
and the dashboard work end to end before a real STT model is dropped in.

Sidecar format: one line per utterance. Lines may carry a start time in seconds,
`[3.20] I need to update my phone number.`; timed lines are assigned to the utterance
whose end time they precede (robust to VAD splitting differently from the script).
Untimed lines are consumed one per utterance. Blank lines and `#` comments are ignored.
"""

from __future__ import annotations

import re
from pathlib import Path

from core import Utterance
from providers.base import STTProvider

_TS = re.compile(r"^\[(\d+(?:\.\d+)?)\]\s*(.*)$")


class StubSTT(STTProvider):
    name = "stub"

    async def transcribe(self, utt: Utterance) -> str:
        return f"[stub STT: {utt.duration:.1f}s of speech]"


class SidecarTranscriptSTT(STTProvider):
    name = "sidecar"

    def __init__(self, lines: list[str]):
        self._pending: list[tuple[float | None, str]] = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = _TS.match(line)
            if m:
                self._pending.append((float(m.group(1)), m.group(2).strip()))
            else:
                self._pending.append((None, line))

    @classmethod
    def from_file(cls, path: Path) -> "SidecarTranscriptSTT":
        return cls(path.read_text(encoding="utf-8").splitlines())

    async def transcribe(self, utt: Utterance) -> str:
        if not self._pending:
            return ""
        if self._pending[0][0] is None:
            return self._pending.pop(0)[1]
        taken: list[str] = []
        # small tolerance: speech onset in the script may slightly precede VAD end.
        while self._pending and self._pending[0][0] is not None and self._pending[0][0] < utt.t_end - 0.05:
            taken.append(self._pending.pop(0)[1])
        return " ".join(taken)

    def finalize(self) -> str:
        rest = " ".join(t for _, t in self._pending)
        self._pending.clear()
        return rest


def sidecar_path_for(wav: Path) -> Path:
    return wav.with_suffix(".txt")
