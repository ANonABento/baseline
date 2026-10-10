"""The AI side's "brain": persona system prompt + chat history -> next spoken line.

`LLMBrain` streams from an OpenAI-compatible endpoint and yields complete sentences as soon as
they are generated, so TTS can start on sentence one while sentence two is still being written.
At most two sentences per turn. `StubBrain` is the offline/test implementation.

The persona LLM is configured independently of the fraud analyzer (CALLER_LLM_* settings,
presets from providers/llm_presets.py):
    CALLER_LLM_PROVIDER  auto (default: nebius if NEBIUS_API_KEY, else ollama) | nebius | nvidia | ollama | stub
    CALLER_LLM_MODEL     optional override of the preset model
        nebius  openai/gpt-oss-120b, reasoning_effort "low"
        ollama  qwen3.5:4b, reasoning_effort "none"
Per turn: the chosen provider; if it errors, returns nothing, or produces no sentence within
CALLER_LLM_FIRST_TIMEOUT_S, local Ollama for that turn; then the persona's scripted line. A call
never goes silent. Reasoning text (gpt-oss "analysis...assistantfinal", <think> blocks) never
reaches TTS: only `delta.content` is read and leaked reasoning prefixes are stripped.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace

from caller.personas import Persona, clean_line, redact, split_first_clause, split_sentences

log = logging.getLogger(__name__)

MAX_SENTENCES = 2
HISTORY_TURNS = 16  # most recent messages sent to the LLM
REASONING_MIN_TOKENS = 600  # reasoning models spend completion tokens on hidden reasoning first


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


# --------------------------------------------------------------------------- reasoning leak guard

_HARMONY_FINAL = re.compile(r"(?:assistant\s*final|<\|channel\|>\s*final\s*<\|message\|>)", re.I)
_ANALYSIS_START = re.compile(r"^\s*(?:<\|channel\|>\s*)?analysis\b", re.I)


def strip_reasoning(buf: str) -> tuple[str, bool]:
    """(speakable text, still_reasoning). Holds back text while a reasoning block is open."""
    if "<think>" in buf:
        if "</think>" not in buf:
            return "", True
        buf = buf.split("</think>")[-1]
    m = None
    for m in _HARMONY_FINAL.finditer(buf):
        pass
    if m is not None:
        return buf[m.end():].lstrip(), False
    if _ANALYSIS_START.match(buf):
        return "", True
    return buf, False


# --------------------------------------------------------------------------- LLM brain


@dataclass
class LLMRoute:
    client: object
    model: str
    provider: str
    reasoning_effort: str | None = None  # None = provider default ("none" for ollama)
    max_tokens: int = 90

    def kwargs(self) -> dict:
        effort = self.reasoning_effort
        if effort is None:
            effort = "none" if self.provider == "ollama" else ""  # qwen3.5 thinks for ~10 s otherwise
        return {"reasoning_effort": effort} if effort else {}


class LLMBrain(Brain):
    def __init__(self, persona: Persona, client, model: str, provider: str, *, timeout_s: float = 10.0,
                 max_tokens: int = 90, temperature: float = 0.7, reasoning_effort: str | None = None,
                 first_timeout_s: float | None = None, fallback: LLMRoute | None = None):
        super().__init__(persona)
        eff_tokens = max_tokens
        if reasoning_effort not in (None, "", "none"):
            eff_tokens = max(max_tokens, REASONING_MIN_TOKENS)
        self.route = LLMRoute(client, model, provider, reasoning_effort, eff_tokens)
        self.fallback = fallback
        self.model = model
        self.provider = provider
        self.name = provider
        self.timeout_s = timeout_s
        self.first_timeout_s = first_timeout_s
        self.temperature = temperature
        self.last_error: str | None = None
        self.last_route: str | None = None  # provider that produced the last reply ("stub" = scripted)

    def _messages(self) -> list[dict]:
        hist = self.history[-HISTORY_TURNS:]
        if hist and hist[0]["role"] == "assistant":
            # chat templates want a user turn first; the opener is the AI's first line
            hist = [{"role": "user", "content": "(call connected)"}] + hist
        if not hist or hist[-1]["role"] != "user":
            hist = hist + [{"role": "user", "content": "(silence)"}]
        return [{"role": "system", "content": self.persona.system_prompt}] + hist

    async def _stream_tokens(self, route: LLMRoute) -> AsyncIterator[str]:
        stream = await route.client.chat.completions.create(
            model=route.model, messages=self._messages(), temperature=self.temperature,
            max_tokens=route.max_tokens, stream=True, **route.kwargs())
        try:
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        finally:
            close = getattr(stream, "close", None) or getattr(stream, "aclose", None)
            if close is not None:
                res = close()
                if asyncio.iscoroutine(res):
                    await res

    async def _reply_from(self, route: LLMRoute, first_timeout: float | None) -> AsyncIterator[str]:
        """Sentences from one route; raises on error / timeout (before or after the first sentence)."""
        raw, consumed, n, t0, first_cut = "", 0, 0, time.monotonic(), False
        tokens = self._stream_tokens(route)
        try:
            while n < MAX_SENTENCES + first_cut:
                limit = first_timeout if (n == 0 and first_timeout) else self.timeout_s
                remaining = limit - (time.monotonic() - t0)
                if remaining <= 0:
                    raise asyncio.TimeoutError(f"no sentence within {limit:.1f} s")
                try:
                    tok = await asyncio.wait_for(tokens.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break
                raw += tok
                speak, reasoning = strip_reasoning(raw)
                if reasoning:
                    continue
                buf = speak[consumed:]
                done, rest = split_sentences(buf)
                if not done and n == 0 and not first_cut:
                    clause, rest2 = split_first_clause(rest)
                    if clause:
                        done, rest, first_cut = [clause], rest2, True
                consumed += len(buf) - len(rest)
                for s in done:
                    line = redact(clean_line(s, 3), self.persona)
                    if line:
                        n += 1
                        yield line
                        if n >= MAX_SENTENCES + first_cut:  # a first-clause cut is not a sentence
                            break
            if n < MAX_SENTENCES + first_cut:
                speak, reasoning = strip_reasoning(raw)
                tail = "" if reasoning else redact(clean_line(speak[consumed:], 3), self.persona)
                if tail:
                    yield tail
        finally:
            await tokens.aclose()

    async def reply(self) -> AsyncIterator[str]:
        routes = [self.route] + ([self.fallback] if self.fallback is not None else [])
        self.last_error = None
        for i, route in enumerate(routes):
            produced = 0
            first_timeout = self.first_timeout_s if (i < len(routes) - 1) else None
            try:
                async for line in self._reply_from(route, first_timeout):
                    produced += 1
                    self.last_route = route.provider
                    yield line
                if produced:
                    return
                self.last_error = f"{route.provider}: empty reply"
            except asyncio.CancelledError:
                raise
            except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001 - never leave the call silent
                self.last_error = f"{route.provider}: {type(e).__name__}: {e}"[:200]
                if produced:
                    return  # half a reply is better than switching voices mid-turn
            log.warning("persona LLM %s failed (%s); %s", route.provider, self.last_error,
                        "trying fallback" if i < len(routes) - 1 else "using scripted line")
        self.last_route = "stub"
        yield self.next_stub_line()


def _caller_shim(settings, provider: str, model: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        llm_provider=provider,
        nebius_api_key=getattr(settings, "nebius_api_key", ""),
        nvidia_api_key=getattr(settings, "nvidia_api_key", ""),
        llm_api_key=getattr(settings, "llm_api_key", ""),
        llm_base_url=getattr(settings, "caller_llm_base_url", ""),
        llm_model=model,
        llm_reasoning_effort=getattr(settings, "caller_llm_reasoning_effort", ""),
    )


def caller_provider_name(settings) -> str:
    """auto -> nebius if NEBIUS_API_KEY else ollama; a keyed provider without its key -> ollama."""
    choice = (getattr(settings, "caller_llm_provider", "auto") or "auto").lower()
    if choice == "stub":
        return "stub"
    if choice == "auto":
        return "nebius" if getattr(settings, "nebius_api_key", "") else "ollama"
    from providers.llm_presets import resolve_provider_name

    name = resolve_provider_name(_caller_shim(settings, choice))
    return "ollama" if name == "stub" else name


def resolve_caller_llm(settings):
    """LLMConfig (provider, base_url, model, api_key, reasoning_effort) for the persona LLM."""
    from providers.llm_presets import LLMConfig, resolve_llm_config

    name = caller_provider_name(settings)
    if name == "stub":
        return LLMConfig("stub")
    return resolve_llm_config(_caller_shim(settings, name, getattr(settings, "caller_llm_model", "")))


def ollama_fallback_config():
    from providers.llm_presets import resolve_llm_config

    return resolve_llm_config(SimpleNamespace(llm_provider="ollama", llm_api_key="", llm_base_url="", llm_model="",
                                              llm_reasoning_effort=""))


class BrainFactory:
    """Builds one Brain per call; shares one HTTP client per route (chosen provider + Ollama fallback)."""

    def __init__(self, settings):
        self.settings = settings
        self.cfg = resolve_caller_llm(settings)
        self.provider, self.model = self.cfg.provider, self.cfg.model
        self.fallback_cfg = ollama_fallback_config() if self.provider not in ("stub", "ollama") else None
        self._clients: dict[str, object] = {}
        log.info("caller LLM: %s %s%s", self.provider, self.model or "",
                 f" (per-turn fallback: ollama {self.fallback_cfg.model})" if self.fallback_cfg else "")

    def info(self) -> dict:
        d = {"provider": self.provider, "model": self.model or None}
        if self.fallback_cfg is not None:
            d["fallback"] = {"provider": "ollama", "model": self.fallback_cfg.model}
        return d

    def _client(self, cfg):
        if cfg.provider not in self._clients:
            from openai import AsyncOpenAI

            self._clients[cfg.provider] = AsyncOpenAI(api_key=cfg.api_key or "none", base_url=cfg.base_url,
                                                      timeout=self.settings.caller_llm_timeout_s, max_retries=0)
        return self._clients[cfg.provider]

    def __call__(self, persona: Persona) -> Brain:
        if self.provider == "stub":
            return StubBrain(persona)
        s = self.settings
        fb = None
        if self.fallback_cfg is not None:
            fb = LLMRoute(self._client(self.fallback_cfg), self.fallback_cfg.model, "ollama",
                          self.fallback_cfg.reasoning_effort or "none", s.caller_llm_max_tokens)
        return LLMBrain(persona, self._client(self.cfg), self.model, self.provider, timeout_s=s.caller_llm_timeout_s,
                        max_tokens=s.caller_llm_max_tokens, temperature=s.caller_llm_temperature,
                        reasoning_effort=self.cfg.reasoning_effort or None,
                        first_timeout_s=s.caller_llm_first_timeout_s if fb is not None else None, fallback=fb)
