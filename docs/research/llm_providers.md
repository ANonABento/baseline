# LLM providers for the fraud analyzer (checked 2026-10-09)

Requirements: one OpenAI-compatible chat call per utterance, a 1-2k-token prompt, strict JSON back, under 1.5 s. Items marked **[UNVERIFIED]** could not be confirmed (we have no API key yet, or the official page is JS-only).

## 1. Nebius Token Factory (primary; $100 credits)
- **Base URL: `https://api.tokenfactory.nebius.com/v1/`**. The docs only use this host. The old `api.studio.nebius.com/v1/` host still responds (it returns 401 with no key), but nothing says how long it will last, so **update `.env.example`**. Sources: [quickstart](https://docs.tokenfactory.nebius.com/quickstart), [switch guide](https://docs.tokenfactory.nebius.com/switch).
- Auth: `Authorization: Bearer $NEBIUS_API_KEY`.
- Structured output: `response_format` takes `{"type":"json_object"}` or `{"type":"json_schema","json_schema":{"name":..,"schema":..,"strict":true}}`. Only models tagged "JSON mode" on their model card support it. The docs also advise putting the schema in the prompt and wrapping `json.loads` in try/except, and some of the docs' own code samples have typos. Source: [JSON docs](https://docs.tokenfactory.nebius.com/ai-models-inference/json).
- Catalog: there's no static list page. Run `GET /v1/models?verbose=true` with the key to get the IDs, prices and limits ([list models](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models)). Many models come in a cheaper base flavor and a `-fast` flavor, e.g. `meta-llama/Meta-Llama-3.1-8B-Instruct-fast`. IDs seen in Sept–Oct 2026 listings: `Qwen/Qwen3-30B-A3B-Instruct-2507`, `Qwen/Qwen3-235B-A22B-Instruct-2507`, `openai/gpt-oss-120b`, `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `google/gemma-3-27b-it`. Whether **Llama-3.1-8B** (our current default) is still served is **[UNVERIFIED]**.
- Pricing: the price list is at [tokenfactory.nebius.com/organization/prices](https://tokenfactory.nebius.com/organization/prices), but the page is JS-rendered and couldn't be read. Small models are reportedly around $0.06–0.20 per 1M tokens, so $100 is effectively unlimited for a hackathon **[UNVERIFIED]**. Rate limits adapt over 15-minute windows; the docs' example baseline is 60 RPM / 400k TPM ([rate limits](https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits)).
- **Pick:**
  - Fastest: `Qwen/Qwen3-30B-A3B-Instruct-2507`, or its `-fast` flavor if `/models` lists one. It's an MoE with 3B active params and no thinking.
  - Best quality: `Qwen/Qwen3-235B-A22B-Instruct-2507`, also no thinking. The docs' JSON example uses the Qwen3-235B family.
  - Avoid `gpt-oss-*` for this path, or set `reasoning_effort:"low"`, because reasoning tokens eat the latency budget.

## 2. NVIDIA API catalog (backup)
- Base URL: `https://integrate.api.nvidia.com/v1`. Auth: `Authorization: Bearer nvapi-...` ([LLM API ref](https://docs.api.nvidia.com/nim/reference/llm-apis)).
- Fast model IDs: `nvidia/nemotron-3.5-lightning-30b-a3b`, `nvidia/nemotron-nano-3-30b-a3b`, `openai/gpt-oss-20b`, `google/gemma-3-12b-it`, `deepseek-ai/deepseek-v4.1-flash`. All of these are in the public `GET /v1/models` list (80 models). The API reference also lists `meta/llama-3.1-8b-instruct` and `meta/llama-3.3-70b-instruct`, but they're missing from `/v1/models` **[UNVERIFIED]**.
- Structured output depends on the backend. vLLM-backed models take `extra_body={"nvext":{"guided_json": schema}}`. Newer and SGLang-backed models take `response_format` with `json_schema`. Test both ([NIM structured generation](https://docs.nvidia.com/nim/large-language-models/1.13.0/structured-generation.html), [container variants](https://docs.nvidia.com/nim/large-language-models/1.15.0/nim-container-variants.html)).
- Limits: about **40 RPM** per model. That figure comes from forums and the dashboard, not an official page, and the free tier is for dev use only. The credit policy is unclear: check your build.nvidia.com dashboard **[UNVERIFIED]**.

## 3. Ollama on the M5 24 GB (offline fallback)
- Install without brew: download [Ollama.dmg](https://ollama.com/download/Ollama.dmg) from [ollama.com/download/mac](https://ollama.com/download/mac) and drag it to Applications.
- Models:
  - `ollama pull qwen3.5:9b`: best quality at 9B or under; supports tools, thinking and vision.
  - `ollama pull qwen3.5:4b`: the speed pick.
  - `-mlx` tags such as `qwen3.5:4b-mlx` run on Apple's MLX engine and are probably faster on Apple Silicon.
  - Alternates: `gemma4:e4b`, `granite4.1:8b`.
- Base URL `http://localhost:11434/v1/`, any API key. The OpenAI-compatible endpoint supports `response_format` (JSON mode). Turn thinking off with `reasoning_effort:"none"` ([OpenAI compat](https://docs.ollama.com/api/openai-compatibility)). The native `/api/chat` takes `format: <json schema>` for strict schemas.
- Latency (estimate, not measured): 9B Q4 prefill runs about 400–800 tok/s and decode about 25–40 tok/s, so a cold 1.5k-token prompt plus about 60 output tokens takes roughly 2.5–4 s. 4B should land around 1–2 s. Ollama reuses the KV cache for an identical prefix, so a fixed system prompt makes warm calls much faster. Keep the model loaded with `OLLAMA_KEEP_ALIVE=-1`.

## 4. Getting under 1.5 s
- **Non-streaming** is fine for short JSON output; streaming doesn't help when you need the whole object. Use `temperature=0`, `max_tokens` of about 150, and keep the output schema tiny: short enum labels, one score, a reason of at most 15 words.
- **Disable thinking/reasoning.** This is the biggest latency trap with Qwen3.x, gpt-oss and Nemotron.
- Put static content (rubric, schema, few-shot) first and the per-utterance text last. That maximizes prefix-cache hits on Ollama/vLLM. Neither Nebius nor NVIDIA documents prompt caching or a cached-token price **[UNVERIFIED]**.
- Gotchas: providers can ignore `response_format` on models that don't support it, and `json_object` isn't a schema, so always validate with Pydantic and fall back to the keyword stub. Set a hard client timeout of about 2 s rather than the current 8 s. Reuse one HTTP client (keep-alive) and send a warm-up call at startup.

## Recommended .env
```
LLM_PROVIDER=auto
NEBIUS_API_KEY=
LLM_BASE_URL=https://api.tokenfactory.nebius.com/v1/
LLM_MODEL=Qwen/Qwen3-30B-A3B-Instruct-2507        # verify exact ID (or -fast flavor) via GET /v1/models
# LLM_MODEL=Qwen/Qwen3-235B-A22B-Instruct-2507    # quality option
LLM_TIMEOUT_S=2
# NVIDIA:  LLM_BASE_URL=https://integrate.api.nvidia.com/v1   LLM_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b  (key nvapi-...; JSON param style unverified)
# Ollama:  LLM_BASE_URL=http://localhost:11434/v1/            LLM_MODEL=qwen3.5:4b   (or qwen3.5:9b; api key = "ollama")
```
