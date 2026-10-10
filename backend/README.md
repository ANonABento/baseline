# Baseline backend

FastAPI + asyncio pipeline: `ingest -> segmenter (VAD) -> per-utterance fan-out (STT + detectors) -> fusion -> events`.

```
app.py            HTTP + WebSocket (/health, /customer, /customers, /clips, POST /replay/{clip}, WS /ws/call)
pipeline.py       CallPipeline (one per call), warmup_models(), analyze_wav() offline helper used by eval/tests
segmenter.py      Segmenter interface; FrameVAD state machine; EnergyVAD (placeholder) / SileroVAD
providers/        STTProvider / LLMProvider interfaces; stub + sidecar STT, MlxWhisperSTT, stub LLM, OpenAI-compatible LLM
detectors/        speaker.py (stub | ECAPA), spoof.py (stub | pretrained | WavLM-LR), prosody.py, fraud.py
ml/               real-model runtime (per-model threads, load-once cache), model wrappers, voiceprint store
kb/fraud_playbook.json   20 fraud / social-engineering patterns with triggers, agent actions, sources
fusion.py         Trust Score + alert levels
events.py         Pydantic event schema (the WS contract, documented in its docstring)
settings.py       pydantic-settings; env vars / .env (see ../.env.example)
```

## WebSocket contract (`ws://localhost:8000/ws/call`)

- Client sends **binary** frames of 16 kHz mono int16 little-endian PCM (live mic), or **JSON** control
  messages: `{"type":"replay","clip":"takeover_clone.wav","customer_id":"CUST-004217"}`,
  `{"type":"start","source":"mic","customer_id":"..."}`, `{"type":"customer","customer_id":"..."}`,
  `{"type":"stop"}`, `{"type":"reset"}`, `{"type":"ping"}`. `customer_id` is optional everywhere;
  it selects whose enrolled voiceprint speaker verification compares against (session default:
  `CUSTOMER_ID`). The `customer` message answers with `status: customer_selected`.
- Server pushes JSON events: `transcript`, `signal`, `trust`, `alert`, `status`. Exact fields are in
  `events.py`. Detector `score` is **risk** in [0, 1] (higher = more suspicious); `confidence` 0 means
  "no opinion" (stubs, too-short utterances, no enrolled voiceprint) and is ignored by fusion.
  `transcript.latency_ms` (optional) is the STT time for that utterance.
- Replay streams the WAV as int16 PCM at real-time pace (`REPLAY_SPEED`) into the same `feed_pcm16`
  path the mic uses. `POST /replay/{clip}` triggers a replay on every connected session.

## Real models (optional `ml` extra)

```bash
cd backend && uv sync --extra ml          # torch, mlx-whisper, silero-vad, speechbrain, transformers, sklearn
# from now on always pass --extra ml (or `make ... ML=1`): plain `uv run` re-syncs and REMOVES the extra
cd .. && make enroll-demo                  # voiceprint for CUST-004217 from a `say -v Samantha` clip
STT_PROVIDER=mlx VAD_PROVIDER=silero SPEAKER_PROVIDER=ecapa SPOOF_PROVIDER=pretrained \
  HF_HUB_OFFLINE=1 make dev-backend ML=1
```

| Stage | Setting | Real implementation | Notes |
|---|---|---|---|
| STT | `STT_PROVIDER=mlx` | `providers/stt_mlx.py` mlx-whisper, `STT_MODEL` (default `mlx-community/whisper-large-v3-turbo`, or `whisper-small-mlx`) | Per utterance, `condition_on_previous_text=False`; segments that look like silence hallucinations are dropped |
| VAD | `VAD_PROVIDER=silero` | `segmenter.SileroVAD`, 512-sample chunks @16 kHz, start at `SILERO_THRESHOLD`, end below threshold-0.15 for `VAD_HANGOVER_MS` | Inline on the event loop (~0.15 ms/chunk); one stateful model per call |
| Speaker | `SPEAKER_PROVIDER=ecapa` | `detectors/speaker.py` SpeechBrain ECAPA (CPU) vs `data/enroll/<customer_id>.npy` | See calibration below |
| Spoof | `SPOOF_PROVIDER=pretrained` | `mo-thecreator/Deepfake-audio-detection` (wav2vec2, labels {0: fake, 1: real}, safetensors, MPS), 4 s windows / 2 s hop | risk = mean P(fake) over windows; confidence capped at `SPOOF_MAX_CONFIDENCE`=0.7 (unproven on modern clones) |
| Spoof | `SPOOF_PROVIDER=wavlm` | frozen `microsoft/wavlm-base-plus` mean-pooled -> our LogisticRegression (`models/spoof_lr.joblib`) | Train with `scripts/train_spoof.py` |

- **Fallbacks:** if a real provider's packages are missing (or `spoof_lr.joblib` doesn't exist) the
  factory logs a warning and uses the stub; if a model fails at runtime the detector emits
  confidence 0 with `detector error: ...`. `/health` and the WS `connected` status show the
  configured providers; `eval.py` records the ones actually used.
- **Threading:** every model has its own single-thread executor (`ml/runtime.py`); loading and
  inference for that model always happen on that thread (MLX streams are per-thread, MPS isn't
  re-entrant). STT, speaker and spoof for one utterance run in parallel; the event loop only awaits.
- **Warmup:** with `WARMUP_MODELS=true` the app's lifespan loads every configured model and runs
  dummy inferences (spoof warms batch sizes 1-3 because MPS compiles per shape) before accepting
  connections: ~7 s warm cache, ~15 s cold.
- **Safety:** only known HF repos from the local cache are loaded; transformers models with
  `use_safetensors=True`. `wavlm-base-plus` ships a pickle on `main`, so we build it from
  `config.json` and load `model.safetensors` from `WAVLM_SAFETENSORS_REVISION` (`refs/pr/2`).
  ECAPA's `.ckpt` files come from the official `speechbrain/` repo. `spoof_lr.joblib` is pickle:
  only load files you trained. `torchaudio.load` is never used (broken without torchcodec).

### Speaker enrollment and calibration

`scripts/enroll.py <customer_id> <wav...> [--name "..."] [--say VOICE]` embeds ~4 s chunks of each
file, averages the L2-normalised embeddings and writes `data/enroll/<id>.npy` + `<id>.json`
(gitignored). The detector reloads a profile when its file changes. Risk from cosine similarity
`s`: a logistic curve through the midpoint of `SPEAKER_ACCEPT_SIM` (0.55, risk 0.10) and
`SPEAKER_REJECT_SIM` (0.30, risk 0.90). Measured per 3-5 s utterance against a 26 s `say`
enrollment: same voice 0.81-0.88, different `say` voice 0.19-0.30 (ECAPA's VoxCeleb EER point is
~0.25-0.30). Real people over a laptop mic / phone will score lower for the same speaker
(typically 0.5-0.7): **recalibrate with team recordings before the demo**. Confidence =
`SPEAKER_MAX_CONFIDENCE` (0.8) x min(1, duration / 3 s); utterances < `SPEAKER_MIN_AUDIO_S` (1 s)
and customers without a voiceprint get confidence 0.

### Training our spoof classifier

`scripts/train_spoof.py data/train/spoof.csv --holdout-speaker <name> [--phone-aug] [--refit-all]`
(CSV: `file,label,speaker`, label fake/real; see the script docstring). It embeds 3 s windows
(1.5 s hop) with frozen WavLM on MPS, fits StandardScaler + LogisticRegression
(class-balanced), prints window- and file-level accuracy / AUC / EER on the held-out speaker(s)
and saves `models/spoof_lr.joblib`. Then `SPOOF_PROVIDER=wavlm`.

### Latency (M5, warm, 3-5 s utterances, measured over data/demo)

| Component | per utterance |
|---|---|
| STT whisper-large-v3-turbo / whisper-small | ~850 ms / ~330 ms |
| Speaker ECAPA (CPU) | 50-90 ms |
| Spoof pretrained / WavLM-LR (MPS) | 85-200 ms |
| End of utterance -> trust event | ~0.85-1.0 s (turbo), ~0.35 s (small): STT dominates |

## Stub mode sidecars

Files next to a demo WAV in `data/demo/`:

- `<clip>.txt` **sidecar transcript**. When the active STT is the stub (the default) the replay path
  and `eval.py` use it as the STT output, so the fraud analyzer and dashboard work end to end. One line
  per utterance, optional start time: `[11.15] I need to wire nine thousand dollars...`. Timed lines
  are assigned to the VAD utterance they fall in; untimed lines are consumed one per utterance;
  leftovers are attached at end of call. Without a sidecar the stub STT emits a placeholder.
  With a real STT, `eval.py` uses it as the reference for WER.
- `<clip>.meta.json` **stub hints** (`{"stub_hints": {"spoof": {"score": .88, "confidence": .8, "reason": "..."}}}`)
  let stub speaker/spoof/prosody detectors return demo values so the dashboard can show a full
  red alert without models. Reasons are prefixed `[stub hint]`. Real detectors and `eval.py`
  ignore them.

## Tests and eval

- `uv run pytest -q`: model-free suite (conftest forces stub providers); ML tests in
  `tests/test_ml_models.py` skip. `uv run --extra ml pytest -q` also runs silero / ECAPA /
  pretrained spoof / mlx-whisper tests from the local HF cache (~10 s).
- `scripts/eval.py` (see its docstring): `labels.csv` takes optional `expected_customer` (active
  customer for the call) and `is_customer` columns to score speaker verification; history rows
  record WER, per-utterance latency and the providers used. Real models are warmed up before timing.

## LLM

Set `NEBIUS_API_KEY` (+ `LLM_BASE_URL`, `LLM_MODEL`) and the OpenAI-compatible provider is used;
any error/timeout/bad JSON falls back to the keyword matcher.
