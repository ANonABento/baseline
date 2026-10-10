"""OpenAI-compatible chat provider (Nebius Token Factory, NVIDIA API, Ollama, ...).
Configured via NEBIUS_API_KEY / LLM_BASE_URL / LLM_MODEL."""

from __future__ import annotations

import asyncio

from openai import AsyncOpenAI

from providers.base import LLMProvider


class OpenAICompatLLM(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, base_url: str, model: str, timeout_s: float = 8.0):
        self.model = model
        self.timeout_s = timeout_s
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=1)

    async def complete(self, system: str, user: str, *, json_mode: bool = True) -> str:
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        resp = await asyncio.wait_for(
            self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.0,
                max_tokens=400,
                **kwargs,
            ),
            timeout=self.timeout_s,
        )
        return resp.choices[0].message.content or ""
