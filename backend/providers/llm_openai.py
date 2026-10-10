"""OpenAI-compatible chat provider (Nebius Token Factory, NVIDIA build.nvidia.com, Ollama).
Provider presets and env selection live in `providers/llm_presets.py`.

JSON mode: asks for `response_format={"type": "json_object"}`. If the endpoint/model rejects
it (HTTP 400/422 mentioning response_format / json), the call is retried once without it and
JSON mode stays off for this client; the fraud detector's lenient parser handles the rest."""

from __future__ import annotations

import asyncio
import logging

import httpx
from openai import AsyncOpenAI, BadRequestError, UnprocessableEntityError

from providers.base import LLMProvider

log = logging.getLogger(__name__)


class OpenAICompatLLM(LLMProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_s: float = 3.0,
        *,
        max_tokens: int = 220,
        json_mode: bool = True,
        provider: str = "openai",
        reasoning_effort: str = "",
        http_client: httpx.AsyncClient | None = None,
    ):
        self.model = model
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.provider = provider
        self.reasoning_effort = reasoning_effort
        self.name = provider
        self._json_mode_ok = json_mode
        # max_retries=0: a retry would blow the ~1.5 s budget; the detector falls back to
        # keywords on any failure instead.
        self._client = AsyncOpenAI(
            api_key=api_key or "none",
            base_url=base_url,
            timeout=timeout_s,
            max_retries=0,
            http_client=http_client,
        )

    async def _create(self, system: str, user: str, json_mode: bool):
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        if self.reasoning_effort:
            # Thinking models (Qwen3.5 on Ollama, gpt-oss) blow the latency budget unless capped.
            kwargs["reasoning_effort"] = self.reasoning_effort
        return await self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0,
            max_tokens=self.max_tokens,
            **kwargs,
        )

    async def complete(self, system: str, user: str, *, json_mode: bool = True) -> str:
        use_json = json_mode and self._json_mode_ok

        async def run():
            nonlocal use_json
            try:
                return await self._create(system, user, use_json)
            except (BadRequestError, UnprocessableEntityError) as e:
                msg = str(e).lower()
                if use_json and ("response_format" in msg or "json" in msg):
                    log.warning("%s rejected response_format; retrying without JSON mode", self.provider)
                    self._json_mode_ok = False
                    use_json = False
                    return await self._create(system, user, False)
                raise

        resp = await asyncio.wait_for(run(), timeout=self.timeout_s)
        if not resp.choices:
            return ""
        return resp.choices[0].message.content or ""
