# Nebius Token Factory research (2026-10-10)

> ## Recommendation
> | Job | Primary | Fallback |
> |---|---|---|
> | Fraud analyzer | `nvidia/Nemotron-3_5-Lightning`, `reasoning_effort: "none"` ($0.06 in / $0.24 out per 1M). ~1.0-1.4 s JSON, always valid, risk 0.9 on the scam test, risk 0.0 with empty patterns on a benign test, verbatim quotes. | `nvidia/Nemotron-3-Ultra-550b-a55b`, `reasoning_effort: "none"` ($1 / $3). ~1.2-1.4 s, same behaviour, larger model so likely sturdier on subtle cases. Alt: `openai/gpt-oss-120b` with `low` (~1.0 s, cheap) but it needs `max_tokens` >= 400-600 or reasoning truncates the JSON. |
> | AI caller | `nvidia/Nemotron-3_5-Lightning`, `none`: TTFT ~0.75 s, total ~0.9 s, short natural replies. | `Qwen/Qwen3-235B-A22B-Instruct-2507` (non-reasoning, no effort param): TTFT ~0.9 s, most varied/natural. |
>
> Key points: (1) For reasoning models use `reasoning_effort: "none"`; `"low"` still burns the 150-token budget on hidden reasoning and returns truncated or empty content. (2) Avoid GLM-5.3-Flash (42 s TTFT), GLM-5.2 (timeouts), DeepSeek-V4-Pro-0813 (10-18 s), Kimi-K2.7-Code (7-10 s). (3) Fine-tuning is NOT realistic tonight (see below); use few-shot prompt plus deterministic post-filters. (4) About 0.7 s of every number is network/queue floor from our location, so a sub-1.5 s analyzer needs short outputs (`max_tokens` ~150, compact JSON).

## Method
`GET /v1/models?verbose=true`, then a throwaway Python harness (not committed). Each config: 2 calls per prompt, temperature 0, max_tokens 150; first pass ran 8 configs in parallel (contention inflates some numbers), then a clean re-run of the top 10 (4 calls each, 3 parallel) gives the table medians. A second benign transcript ("check my balance, give DOB + last 4 SSN for verification") tested false alarms, with an added "score benign calls near 0" line in the system prompt. Total spend well under $0.20. Skipped: Qwen3-Embedding-8B, MiniCPM-V-4.5 (vision).

Parameter notes: `reasoning_effort` with `low` or `none` is accepted by every model except `openai/gpt-oss-120b`, which rejects `none` (400 "Harmony does not support reasoning_effort='none'"; use `low`). Reasoning arrives in a separate `reasoning_content`/`reasoning` field, never inside `content` (no `<think>` leakage seen). `none` removes reasoning for Kimi-K3, GLM-5.1, Nemotron-3_5-Lightning, Nemotron Ultra/Super, DeepSeek-V4-Flash, Qwen3.8/3.5, DeepSeek-V4-Pro. It does not disable it for MiniMax-M3 or Kimi-K2.6/K2.7 (field still present; MiniMax latency still fine).

## Benchmark (clean re-run, medians, seconds)
| Model (config) | $/1M in / out | Analyzer JSON | Persona TTFT | Persona total | Valid JSON @150 tok | Benign risk | Notes |
|---|---|---|---|---|---|---|---|
| nvidia/Nemotron-3_5-Lightning (none) | 0.06 / 0.24 | 1.44 | 0.76 | 0.90 | yes (no only without `none`) | 0.0 | best overall; verbatim quotes, generic ids p1..p3; natural caller |
| nvidia/Nemotron-3-Ultra-550b (none) | 1 / 3 | 1.38 | 0.91 | 1.05 | yes | 0.0 | descriptive ids, 3 verbatim quotes, risk 0.85 |
| nvidia/nemotron-3-super-120b (none) | 0.3 / 0.9 | 1.35 | 1.00 | 1.25 | yes | 0.1 plus a false PII pattern | false alarm; missed "new phone" pattern; avoid |
| openai/gpt-oss-120b (low) | 0.15 / 0.6 | 1.05 | 0.80 | 0.97 | only with max_tokens >= ~400 | 0.02-0.05 | fastest JSON; persona content EMPTY at 150 tokens (reasoning uses budget) |
| MiniMaxAI/MiniMax-M3 (default) | 0.3 / 1.2 | 1.43 | 1.02 | 1.58 | yes | 0.0 | good quotes (partial sentences); reasoning field always present, content clean |
| deepseek-ai/DeepSeek-V4-Flash-0731 (none) | 0.14 / 0.28 | 1.66 | 1.09 | 1.29 | yes (no without `none`) | 0.02 | good analysis, slightly over 1.5 s |
| Qwen/Qwen3-235B-A22B-Instruct-2507 | 0.2 / 0.6 | 2.49 | 0.90 | 1.63 | yes | 0.1 | most natural persona; too slow for analyzer |
| Qwen/Qwen3-30B-A3B-Instruct-2507 | 0.1 / 0.3 | 1.86 | 0.78 | 1.11 | yes | 0.0 | good; first-pass run had 3-9 s spikes (variable) |
| google/gemma-3-27b-it | 0.1 / 0.3 | 2.62 | 0.79 | 1.21 | yes | 0.7 (false alarm) | generic ids "P101"; flagged benign DOB sharing; reject |
| zai-org/GLM-5.1 (none) | 1.4 / 4.4 | 3.90 | 0.71 | 1.17 | yes with `none` | n/t | too slow and pricey |

First-pass only (contended, 2 runs each), JSON median / persona TTFT:
- Kimi-K3: none 2.1 s valid / 1.27 s; low and default invalid (reasoning). $3/$15.
- Qwen3.8-27B: 3.1-5.5 s, invalid JSON in all modes; TTFT 1.1-1.5 s.
- Qwen3.5-397B-A17B: 2.2 s, invalid in all modes; TTFT 0.9-1.0 s.
- DeepSeek-V4-Pro: 1.7-2.0 s, invalid in all modes; TTFT ~0.95 s. DeepSeek-V4-Pro-0813: 4.7 s (none) to 10 s; TTFT 1.3-1.6 s.
- DeepSeek-V4.1-Flash: 1.5-1.7 s, invalid in all modes; TTFT 1.1 s.
- Hermes-4-405B: 3.1 s valid, TTFT 0.75 s, no reasoning; $1/$3.
- NVIDIA-Nemotron-3-Nano-30B-A3B: 1.4 s but EMPTY content in all modes; TTFT 0.8 s.
- Kimi-K2.6: 1.8 s invalid; Kimi-K2.7-Code: 7-9 s JSON, 10 s persona.
- GLM-5.3: 1.8-2.4 s invalid; GLM-5.3-Flash: 35 s JSON, 42 s TTFT; GLM-5.2: 60 s read timeouts.

"Invalid JSON" here mostly means output cut off at the 150-token cap by reasoning, not malformed JSON; raising max_tokens would fix it at a latency cost.

Caveats: one scam and one benign transcript, ~100-token prompt (not the real ~1.1k-token prompt). Re-run on the labelled set in `results/` with the real prompt before locking in. Per-model rate limits come from the verbose list (e.g. Kimi-K3 1000 RPM / 2M TPM).

## Fine-tuning on Token Factory
Sources: [overview](https://docs.tokenfactory.nebius.com/fine-tuning/overview), [how to fine-tune](https://docs.tokenfactory.nebius.com/fine-tuning/how-to-fine-tune), [datasets](https://docs.tokenfactory.nebius.com/fine-tuning/datasets), [base models](https://docs.tokenfactory.nebius.com/post-training/models.md), [deploy custom model](https://docs.tokenfactory.nebius.com/fine-tuning/deploy-custom-model), [launch blog](https://nebius.com/blog/posts/fine-tuning-launches-on-nebius-ai-studio).
- Methods: LoRA or full fine-tuning through the OpenAI-style API (`client.fine_tuning.jobs.create`; `lora: true`, `lora_r` 8-128, `n_epochs` 1-20 default 3, `batch_size` 8-32, lr default 1e-5, optional validation file 10-20%). Checkpoint saved each epoch; poll no faster than every 15 s.
- Base models: LoRA+full for Qwen3 (0.6B-32B dense; 30B-A3B and 235B-A22B MoE incl. Instruct-2507), Qwen2.5 (0.5B-72B), gpt-oss-20b/120b (Unsloth BF16), Llama 3.1/3.2/3.3. Full only: Gemma-4 E2B/E4B/31B, Qwen3.5/3.6-27B, DeepSeek V3-0324 / V4-Flash. Context 8k default, up to 131k via `context_length`.
- Data: `.jsonl` uploaded with `purpose="fine-tune"`; one `{"messages":[{role,content},...]}` per line (also prompt/completion and plain text), up to 5 GB per file.
- Cost and turnaround: not published in the docs I could reach (no ETA, no price list found). Billed by training tokens; a few hundred ~1.2k-token examples x 3 epochs is only a few million tokens, so cost is likely small versus $100, but queue and run time are unknown.
- Deployment: after the job succeeds, list checkpoints and download result files, then deploy the LoRA as a serverless adapter (UI or API, per-token billing, text-to-text only). Caveat from the models page: Meta (Llama) models are deployable on Dedicated endpoints only, and GPT-OSS MoE adapters must be merged for Dedicated. Serverless looks most plausible for Qwen dense bases, unverified. Deploy time is undocumented.
- Verdict: technically possible (e.g. Qwen3-8B/4B LoRA) but NOT realistic in ~4 hours tonight. Unknown queue time and deploy path, adapter latency may not beat Nemotron-3_5-Lightning's ~1 s, and we would need hundreds of labelled transcripts plus a held-out eval; most of the time would go to data prep and waiting. Better: few-shot examples and a strict rubric in the prompt, plus deterministic filters (quotes must be verbatim substrings of the transcript, require >= 2 patterns or a risk threshold, hysteresis across consecutive utterances) to cut false alarms. Optional stretch: start a Qwen3-8B LoRA job in the background with a go/no-go on a held-out set.

## .env snippet
```
LLM_BASE_URL=https://api.tokenfactory.nebius.com/v1/
LLM_MODEL=nvidia/Nemotron-3_5-Lightning
CALLER_LLM_MODEL=nvidia/Nemotron-3_5-Lightning
LLM_REASONING_EFFORT=none
# fallbacks
# LLM_MODEL=nvidia/Nemotron-3-Ultra-550b-a55b          (effort none)
# CALLER_LLM_MODEL=Qwen/Qwen3-235B-A22B-Instruct-2507  (do not send reasoning_effort)
# openai/gpt-oss-120b: LLM_REASONING_EFFORT=low and max_tokens >= 400
```
Send `reasoning_effort` only to models that accept it (all accept `none`/`low` except gpt-oss, which rejects `none`). Non-reasoning models (Qwen3 Instruct, Hermes, gemma) accepted it without error in the benchmark but it has no effect.

## Full model list (GET /v1/models?verbose=true, 25 models)
Prices converted to USD per 1M tokens. The API returns no explicit JSON-mode or "fast" flag; `supported_features` only ever shows tools / reasoning. No cache-read pricing listed.

| Model | Ctx | $/1M in | $/1M out | Quant | Features | Region |
|---|---|---|---|---|---|---|
| moonshotai/Kimi-K3 | 1,024,000 | 3 | 15 | fp4 | tools, reasoning | FR |
| Qwen/Qwen3-235B-A22B-Instruct-2507 | 262,144 | 0.2 | 0.6 | fp8 | tools, json_mode, structured_outputs | FI |
| google/gemma-3-27b-it | 110,000 | 0.1 | 0.3 | fp8 | tools | FI |
| Qwen/Qwen3-Embedding-8B | 40,960 | 0.01 | 0 | - | - | FI |
| openai/gpt-oss-120b | 131,072 | 0.15 | 0.6 | fp4 | tools, json_mode, structured_outputs, reasoning | FI |
| Qwen/Qwen3-30B-A3B-Instruct-2507 | 262,144 | 0.1 | 0.3 | fp8 | tools, json_mode, structured_outputs | FI |
| NousResearch/Hermes-4-405B | 131,072 | 1 | 3 | fp8 | tools, json_mode, structured_outputs, reasoning | FI |
| nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B | 262,144 | 0.06 | 0.24 | fp8 | tools, reasoning | FI |
| zai-org/GLM-5.1 | 202,752 | 1.4 | 4.4 | fp8 | tools, json_mode, structured_outputs, reasoning | FI |
| nvidia/Nemotron-3_5-Lightning | 1,048,576 | 0.06 | 0.24 | bf16 | tools, reasoning | FI |
| openbmb/MiniCPM-V-4_5 | 32,000 | 0.658 | 1.11 | fp16 | json_mode, structured_outputs | FI |
| Qwen/Qwen3.8-27B | 262,144 | 0.45 | 3 | fp4 | tools, reasoning | US |
| deepseek-ai/DeepSeek-V4-Flash-0731 | 1,024,000 | 0.14 | 0.28 | fp8 | tools, json_mode, structured_outputs, reasoning | US |
| MiniMaxAI/MiniMax-M3 | 1,048,576 | 0.3 | 1.2 | fp4 | tools, reasoning | US |
| moonshotai/Kimi-K2.7-Code | 262,144 | 0.95 | 4 | fp4 | tools, reasoning | US |
| nvidia/Nemotron-3-Ultra-550b-a55b | 1,048,576 | 1 | 3 | fp4 | tools, reasoning | US |
| moonshotai/Kimi-K2.6 | 262,144 | 0.95 | 4 | int4 | tools, reasoning | US |
| nvidia/nemotron-3-super-120b-a12b | 262,144 | 0.3 | 0.9 | fp4 | tools, reasoning | US |
| Qwen/Qwen3.5-397B-A17B | 262,144 | 0.6 | 3.6 | fp4 | tools, reasoning | US |
| deepseek-ai/DeepSeek-V4-Pro | 1,048,576 | 1.75 | 3.5 | fp8 | tools, json_mode, structured_outputs, reasoning | UK |
| deepseek-ai/DeepSeek-V4-Pro-0813 | 979,000 | 1.32 | 3.96 | fp8 | tools, reasoning | UK |
| zai-org/GLM-5.2 | 1,048,576 | 1.4 | 4.4 | fp4 | tools, reasoning | UK |
| zai-org/GLM-5.3-Flash | 1,024,000 | 0.15 | 0.5 | fp4 | tools, reasoning | US |
| deepseek-ai/DeepSeek-V4.1-Flash | 1,048,000 | 0.3 | 1.2 | fp8 | - | US |
| zai-org/GLM-5.3 | 1,024,000 | 1.4 | 4.4 | fp4 | tools, reasoning | US |