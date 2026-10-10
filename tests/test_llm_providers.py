"""Provider preset selection and the OpenAI-compatible client against mocked HTTP."""

import asyncio
import json

import httpx
import pytest

from detectors.fraud import FraudDetector
from providers import make_llm
from providers.llm_openai import OpenAICompatLLM
from providers.llm_presets import PRESETS, build_llm, resolve_llm_config
from providers.llm_stub import StubLLM
from settings import Settings

ENV_KEYS = ["LLM_PROVIDER", "NEBIUS_API_KEY", "NVIDIA_API_KEY", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"]


@pytest.fixture
def mk(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)

    def _mk(**kw):
        return Settings(_env_file=None, **kw)

    return _mk


# ---------------------------------------------------------------- preset selection

def test_auto_without_keys_is_stub(mk):
    s = mk()
    assert s.resolved_llm_provider() == "stub"
    assert isinstance(make_llm(s), StubLLM)


def test_auto_prefers_nebius_then_nvidia(mk):
    assert mk(nebius_api_key="n", nvidia_api_key="v").resolved_llm_provider() == "nebius"
    assert mk(nvidia_api_key="v").resolved_llm_provider() == "nvidia"


@pytest.mark.parametrize("provider,key_kw", [("nebius", "nebius_api_key"), ("nvidia", "nvidia_api_key")])
def test_explicit_presets(mk, provider, key_kw):
    s = mk(llm_provider=provider, **{key_kw: "secret"})
    cfg = resolve_llm_config(s)
    assert cfg.provider == provider
    assert cfg.base_url == PRESETS[provider].base_url and cfg.model == PRESETS[provider].model
    assert cfg.api_key == "secret"
    llm = make_llm(s)
    assert isinstance(llm, OpenAICompatLLM) and llm.provider == provider and llm.model == cfg.model


def test_explicit_preset_without_key_degrades_to_stub(mk):
    s = mk(llm_provider="nvidia", nebius_api_key="n")
    assert s.resolved_llm_provider() == "stub"
    assert isinstance(make_llm(s), StubLLM)


def test_ollama_needs_no_key(mk):
    s = mk(llm_provider="ollama")
    cfg = resolve_llm_config(s)
    assert cfg.provider == "ollama" and cfg.base_url.startswith("http://localhost:11434") and cfg.api_key
    assert isinstance(make_llm(s), OpenAICompatLLM)


def test_overrides_and_legacy_alias(mk):
    s = mk(llm_provider="openai", nebius_api_key="n", llm_base_url="https://x.example/v1/", llm_model="my/model")
    cfg = resolve_llm_config(s)
    assert (cfg.provider, cfg.base_url, cfg.model, cfg.api_key) == ("nebius", "https://x.example/v1/", "my/model", "n")
    s2 = mk(llm_provider="nvidia", llm_api_key="generic")
    assert resolve_llm_config(s2).api_key == "generic"


def test_env_vars_select_preset(monkeypatch, mk):
    mk()  # clears env
    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "from-env")
    s = Settings(_env_file=None)
    assert resolve_llm_config(s).api_key == "from-env" and s.resolved_llm_provider() == "nvidia"


# ---------------------------------------------------------------- mocked HTTP

def completion(content):
    return {
        "id": "cmpl-1", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def client_with(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


TAKEOVER_UTTS = [
    (0, "Hi, I need to update the phone number on my account."),
    (1, "Once that's done, I need to wire nine thousand dollars to a new account today."),
]


async def test_request_shape_and_end_to_end_evidence(mk):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion(json.dumps({
            "risk": 0.9, "confidence": 0.8, "reason": "ATO",
            "patterns": [{"id": "ato_contact_change_then_money", "u": 1, "quote": "wire nine thousand dollars to a new account"}],
        })))

    s = mk(llm_provider="nebius", nebius_api_key="sk-test", llm_model="test/model")
    llm = build_llm(s, http_client=client_with(handler))
    r = await FraudDetector(llm).analyze(None, _ctx(TAKEOVER_UTTS))

    assert seen["url"].startswith(PRESETS["nebius"].base_url.rstrip("/")) and seen["url"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer sk-test"
    body = seen["body"]
    assert body["model"] == "test/model" and body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] <= 300 and body["temperature"] == 0.0
    assert "[u1] Once that's done" in body["messages"][1]["content"]

    assert r.details["engine"] == "llm" and r.details["model"] == "test/model"
    p = r.details["patterns"][0]
    assert p["id"] == "ato_contact_change_then_money" and p["utterance_id"] == 1
    assert p["quote"] == "wire nine thousand dollars to a new account"
    assert r.details["citations"][0]["pattern_id"] == p["id"]


async def test_json_mode_rejected_retries_without_response_format():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("response_format" in body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format is not supported for this model"}})
        return httpx.Response(200, json=completion('{"risk": 0.1, "patterns": []}'))

    llm = OpenAICompatLLM("k", "https://mock.local/v1/", "m", http_client=client_with(handler))
    assert await llm.complete("s", "u") == '{"risk": 0.1, "patterns": []}'
    assert await llm.complete("s", "u")
    assert calls == [True, False, False]  # JSON mode remembered as unsupported


async def test_http_error_falls_back_to_keywords():
    llm = OpenAICompatLLM("k", "https://mock.local/v1/", "m",
                          http_client=client_with(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}})))
    a = await FraudDetector(llm).assess(TAKEOVER_UTTS)
    assert a.method == "keyword" and a.engine == "keywords" and a.score >= 0.8
    assert a.evidence and a.evidence[0].utterance_id == 1


async def test_http_timeout_falls_back_to_keywords():
    async def slow(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json=completion("{}"))

    llm = OpenAICompatLLM("k", "https://mock.local/v1/", "m", timeout_s=0.1, http_client=client_with(slow))
    a = await asyncio.wait_for(FraudDetector(llm, timeout_s=0.2).assess(TAKEOVER_UTTS), timeout=3)
    assert a.method == "keyword" and a.score >= 0.8


async def test_unparseable_completion_falls_back_to_keywords():
    llm = OpenAICompatLLM("k", "https://mock.local/v1/", "m",
                          http_client=client_with(lambda r: httpx.Response(200, json=completion("I can't help with that."))))
    a = await FraudDetector(llm).assess(TAKEOVER_UTTS)
    assert a.method == "keyword" and a.score >= 0.8


async def test_empty_choices_falls_back():
    body = completion("x")
    body["choices"] = []
    llm = OpenAICompatLLM("k", "https://mock.local/v1/", "m", http_client=client_with(lambda r: httpx.Response(200, json=body)))
    a = await FraudDetector(llm).assess(TAKEOVER_UTTS)
    assert a.method == "keyword"


def _ctx(utts):
    import numpy as np

    from core import CallContext, Utterance

    ctx = CallContext()
    for uid, text in utts:
        ctx.utterances.append(Utterance(id=uid, audio=np.zeros(10, np.float32), sample_rate=16000, t_start=0, t_end=1, text=text))
    return ctx
