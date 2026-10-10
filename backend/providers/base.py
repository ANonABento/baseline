"""Provider interfaces. Implementations must be safe to call from asyncio; run blocking
model inference in a thread (`asyncio.to_thread`) so the event loop keeps streaming."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core import Utterance


class STTProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def transcribe(self, utt: Utterance) -> str:
        """Return the text for one utterance ("" if nothing intelligible)."""

    def finalize(self) -> str:
        """Called at end of call; may return leftover text to attach to the last utterance."""
        return ""


class LLMProvider(ABC):
    name: str = "base"
    is_stub: bool = False

    @abstractmethod
    async def complete(self, system: str, user: str, *, json_mode: bool = True) -> str:
        """Return the raw model output (expected to be JSON when json_mode=True).
        May raise on network/timeout errors; callers must handle that."""
