"""The AI side's "brain": persona system prompt + chat history -> next spoken line.

`LLMBrain` streams from an OpenAI-compatible endpoint (Ollama by default, same presets as the
fraud analyzer; CALLER_LLM_* settings) and yields complete sentences as soon as they are
generated, so TTS can start on sentence one while sentence two is still being written. At most
two sentences per turn. Any error/timeout falls back to the persona's scripted stub lines, so a
call never goes silent. `StubBrain` is the offline/test implementation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from types import SimpleNamespace

from caller.personas import Persona, clean_line, split_sentences

log = logging.getLogger(__name__)

MAX_SENTENCES = 2
HISTORY_TURNS = 16  # most recent messages sent to the LLM


class Brain(ABC):
    name: str = "base"
    model: str | None = None

    def __init__(self, persona: Persona):
        self.persona = persona
        self.history: list[dict] = []  # [{"role": "assistant"|"user", "content": str}]
        self._stub_i = 0

    def add_ai(self, text: str) -> None:
        if text:
            self.history.append({"role": "assistant", "content": text})

    def add_visitor(self, text: str) -> None:
        if not text:
            return
        if self.history and self.history[-1]["role"] == "user":  # merge back-to-back visitor lines
            self.history[-1]["content"] += " " + text
        else:
            self.history.append({"role": "user", "content": text})

    def next_stub_line(self) -> str:
        lines = self.persona.stub_lines
        line = lines[self._stub_i % len(lines)]
        self._stub_i += 1
        return line

    @abstractmethod
    def reply(self) -> AsyncIterator[str]:
        """Yield the next turn sentence by sentence (cleaned, <= MAX_SENTENCES)."""


class StubBrain(Brain):
    name = "stub"

    async def reply(self) -> AsyncIterator[str]:
        line = self.next_stub_line()
        for s in split_sentences(line + " ")[0] or [line]:
            yield s


class LLMBrain(Brain):
    def __init__(self, persona: Persona, client, model: str, provider: str, *, timeout_s: float = 10.0,
                 max_tokens: int = 90, temperature: float = 0.7):
        super().__init__(persona)
        self.client = client
        self.model = model
        self.provider = provider
        self.name = provider
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.last_error: str | None = None

    def _messages(self) -> list[dict]:
        hist = self.history[-HISTORY_TURNS:]
        if hist and hist[0]["role"] == "assistant":
            # chat templates want a user turn first; the opener is the AI's first line
            hist = [{"role": "user", "content": "(call connected)"}] + hist
        if not hist or hist[-1]["role"] != "user":
            hist = hist + [{"role": "user", "content": "(silence)"}]
        return [{"role": "system", "content": self.persona.system_prompt}] + hist

    async def _stream_tokens(self) -> AsyncIterator[str]:
        kwargs = {}
        if self.provider == "ollama":
            kwargs["reasoning_effort"] = "none"  # qwen3.5 thinks for ~10 s otherwise
        stream = await self.client.chat.completions.create(
            model=self.model, messages=self._messages(), temperature=self.temperature,
            max_tokens=self.max_tokens, stream=True, **kwargs)
        try:
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                res = close()
                if asyncio.iscoroutine(res):
                    await res

    async def reply(self) -> AsyncIterator[str]:
        buf, n, t0 = "", 0, time.monotonic()
        tokens = self._stream_tokens()
        try:
            while n < MAX_SENTENCES:
                remaining = self.timeout_s - (time.monotonic() - t0)
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    tok = await asyncio.wait_for(tokens.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break
                buf += tok
                if "<think>" in buf and "</think>" not in buf:
                    continue
                done, buf = split_sentences(buf)
                for s in done:
                    line = clean_line(s, 1)
                    if line:
                        n += 1
                        yield line
                        if n >= MAX_SENTENCES:
                            break
            if n < MAX_SENTENCES:
                tail = clean_line(buf, 1)
                if tail:
                    n += 1
                    yield tail
        except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001 - never leave the call silent
            if isinstance(e, asyncio.CancelledError):
                raise
            self.last_error = f"{type(e).__name__}: {e}"[:200]
            log.warning("persona LLM failed (%s); using scripted line", self.last_error)
            if n == 0:
                yield self.next_stub_line()
        finally:
            await tokens.aclose()
        if n == 0 and not self.last_error:
            yield self.next_stub_line()  # model produced nothing usable


def resolve_caller_llm(settings) -> tuple[str, str, str, str]:
    """(provider, base_url, model, api_key) for the persona LLM; provider "stub" if unusable."""
    from providers.llm_presets import resolve_llm_config

    shim = SimpleNamespace(
        llm_provider=getattr(settings, "caller_llm_provider", "ollama"),
        nebius_api_key=getattr(settings, "nebius_api_key", ""),
        nvidia_api_key=getattr(settings, "nvidia_api_key", ""),
        llm_api_key=getattr(settings, "llm_api_key", ""),
        llm_base_url=getattr(settings, "caller_llm_base_url", ""),
        llm_model=getattr(settings, "caller_llm_model", ""),
    )
    cfg = resolve_llm_config(shim)
    return cfg.provider, cfg.base_url, cfg.model, cfg.api_key


class BrainFactory:
    """Builds one Brain per call; shares a single HTTP client."""

    def __init__(self, settings):
        self.settings = settings
        self.provider, self.base_url, self.model, self.api_key = resolve_caller_llm(settings)
        self._client = None

    def info(self) -> dict:
        return {"provider": self.provider, "model": self.model or None}

    def __call__(self, persona: Persona) -> Brain:
        if self.provider == "stub":
            return StubBrain(persona)
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.api_key or "none", base_url=self.base_url,
                                       timeout=self.settings.caller_llm_timeout_s, max_retries=0)
        s = self.settings
        return LLMBrain(persona, self._client, self.model, self.provider, timeout_s=s.caller_llm_timeout_s,
                        max_tokens=s.caller_llm_max_tokens, temperature=s.caller_llm_temperature)
