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
live_api.py       public "try it live" API: /api/config, POST /api/session, WS /ws/session/{id}, /api/report(s)
sessions.py       live-call FIFO queue + slots (MAX_CONCURRENT_CALLS), ETA, reconnect grace
caller/           AI side of a live call: personas.py (prompts), brain.py (persona LLM), tts.py
                  (ElevenLabs | say | stub), live_call.py (turn-taking, barge-in, analysis), report.py
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
# careful: a later plain `uv sync` (or `make setup` without ML=1) removes the extra again
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

## Live call API

Public Omegle-style experience: a visitor picks a role, waits in a FIFO queue, then talks live to an AI
while Baseline analyzes the call. Run with real models: `make dev-live` (STT mlx, VAD silero, speaker
ECAPA, spoof pretrained, persona LLM Ollama `qwen3.5:4b`, `HF_HUB_OFFLINE=1`; enrolls CUST-004217 first if
`data/enroll` is missing). CORS allows any origin (covers the Vite dev server).

| role | visitor plays | AI plays | Baseline analyzes |
|---|---|---|---|
| `agent` | the bank agent | a fraudster calling as Margaret Chen (CUST-004217), per `scenario` | the AI caller's TTS audio vs Margaret's voiceprint; its LLM text is the transcript (no STT) |
| `scammer` | a fraudster trying to take over Margaret's account | a polite bank agent ("Jordan", First Harbor Bank) who follows verification procedure | the visitor's mic (VAD + STT + all detectors) vs Margaret's voiceprint |

The `say` voice `Samantha` is the voice Margaret's demo voiceprint was enrolled from, so in role `agent`
it plays a perfect clone (speaker check passes; spoof + fraud catch it).

### HTTP

- `GET /api/config` ->
  `{roles:["agent","scammer"], scenarios:[{id,label}], voices:[{id,label}], max_concurrent, queue_length,
  active_calls, tts:"elevenlabs"|"say"|"stub", llm:{provider, model}}`.
  Scenarios: `account_takeover`, `grandparent_coached`, `safe_account`, `verification_evasion`.
  Voices: `say` voices without an ElevenLabs key; with `ELEVENLABS_API_KEY`, the `ELEVENLABS_VOICES` list
  (`Label:id,Label 2:id2`; default `ELEVENLABS_VOICE_ID` or the first entry) or premade voices.
  (`tts:"stub"` only appears off-macOS without a key.)
- `POST /api/session` body `{role, scenario, voice}`, each optional and `"random"` by default ->
  `{session_id, ws_url}` (`ws_url` is absolute, `ws://`/`wss://` from the request host). 400 on an
  unknown value. Randoms are resolved here. A session that never connects is dropped after 60 s.
- `GET /api/report/{id}` -> the full report (404 if unknown). `GET /api/reports?limit=20` -> newest
  first: `[{id, created_at, role, scenario, voice, ended_reason, call_s, level, label, trust, caught, turns}]`.

### WebSocket `/ws/session/{session_id}`

Client -> server:
- binary: visitor mic, 16 kHz mono int16 LE PCM (any frame size; 20-100 ms recommended). Ignored while
  queued. Use `echoCancellation: true` on getUserMedia, or the AI's voice from the speakers will barge in.
- JSON `{"type":"hangup"}` (ends the call, or leaves the queue), `{"type":"ping"}`,
  `{"type":"text","text":"..."}` (typed visitor utterance, skips STT; in role `scammer` it is analyzed
  by the text detectors).

Server -> client JSON:
- `{"type":"queue","position","queue_length","eta_s"}`: on connect and every change, refreshed every 5 s
  while waiting. `position` is 1-based; a visitor who gets a slot immediately receives one event with
  `position: 0` right before `call_started`. ETA = simulated hand-off using the average measured call
  length (seed 120 s, capped at `MAX_CALL_SECONDS`).
- `{"type":"call_started","session_id","role","scenario","voice","customer":{"id","name","account_mask",
  "enrolled"},"audio":{"sample_rate":16000,"format":"pcm_s16le"},"max_call_s"}`. The AI speaks first.
- `{"type":"speaking","who":"ai"|"visitor","state":"start"|"end"}`. AI start = first audio frame sent;
  AI end = when the client has finished playing it (or on barge-in). Visitor start/end come from the VAD.
- `{"type":"ai_level","rms":0..1}`: ~20 Hz while the AI speaks, aligned with playback time.
- `{"type":"stop_audio"}`: barge-in (the visitor spoke for `BARGE_IN_MS`=350 ms over the AI): flush any
  buffered AI audio now.
- `{"type":"transcript", ...TranscriptEvent fields..., "speaker":"ai"|"visitor", "analyzed":bool}`.
  `analyzed:true` lines went through the pipeline; their `utterance_id` (0, 1, ...) is what `signal`
  and `trust` events reference. `analyzed:false` lines (the side Baseline does not analyze) use
  `utterance_id` >= 1000 so they never collide. AI lines are sent when the AI finishes its turn (an
  interrupted line ends with ` —`). `t_start`/`t_end` are seconds since call start.
- `signal`, `trust`, `alert`: unchanged pipeline events (see above / `events.py`).
- `{"type":"warning","message","seconds_left"}`: `CALL_WARNING_SECONDS` (30) before the hard cap.
- `{"type":"call_ended","reason":"hangup"|"timeout"|"error","report_id","reveal":{"role","scenario",
  "persona_label","voice","tts"}}`, sent after the final analysis flush and report save.
- `{"type":"error","message"}`: unknown/expired session (the socket then closes with 4404), a second
  connection to an active call (4409), bad frames, server errors. `{"type":"pong"}` answers a ping during
  a call (while queued, a ping is answered with a `queue` event).

Server -> client binary: AI voice, 16 kHz mono int16 LE PCM, 50 ms frames, sent at real time plus a
250 ms lead (`AUDIO_LEAD_MS`), so the client can simply queue and play them.

`TranscriptEvent` gained two OPTIONAL fields, `speaker` and `analyzed` (additive; `null` on `/ws/call`).

Queue rules: FIFO, `MAX_CONCURRENT_CALLS` (1) slots, calls capped at `MAX_CALL_SECONDS` (240). Closing the
socket during a call ends it and frees the slot immediately (report saved with reason `hangup`). A queued
visitor who reconnects to the same `ws_url` within `RECONNECT_GRACE_S` (10 s) keeps their place; while
they are away the next connected visitor may take a free slot.

### Report (`data/reports/<id>.json`, gitignored)

`{id, created_at, ended_reason, meta:{role, scenario, scenario_label, voice, tts, llm, persona:{label,
summary}, customer, analyzed_channel, requested, providers}, durations:{queue_wait_s, call_s},
transcript:[{utterance_id, speaker, analyzed, text, t_start, t_end, latency_ms}], signals:[...+t],
trust:[...+t], alerts:[...+t], verdict:{level, label, trust, fired, signals_fired_ever, reasons,
suggested_action, caught, final_signals}, fraud_evidence:[pattern...], latencies:{turns:[{turn, source,
visitor_end_to_first_audio_ms, llm_first_sentence_ms, tts_first_audio_ms, stt_ms?,
speech_end_to_first_audio_ms?}], mean_turn_ms, p50_turn_ms, max_turn_ms, pipeline:[...]}, errors}`.
`caught` = an alert was raised (the fraudster side is always a fraudster in this simulation).

### AI side

- Persona prompts (`caller/personas.py`) frame every call as an authorized fraud-training simulation;
  replies are at most 2 short sentences, cleaned of stage directions/labels/emojis. The bank-agent
  persona never reveals record details: any line containing the DOB/ZIP/phone is replaced by a refusal.
  Openers are canned (zero latency); later turns stream from the LLM sentence by sentence into TTS (the
  first chunk is cut at a comma if the first sentence runs long). Any LLM error/timeout -> a scripted line.
- Persona LLM: `CALLER_LLM_PROVIDER` (default `ollama`; `reasoning_effort:"none"` is always sent to
  Ollama), `CALLER_LLM_MODEL`, `CALLER_LLM_TIMEOUT_S`, `CALLER_LLM_MAX_TOKENS`, `CALLER_LLM_TEMPERATURE`.
- TTS: `TTS_PROVIDER=auto` -> `ElevenLabsTTS` (streaming, `pcm_16000`, `ELEVENLABS_MODEL`
  `eleven_flash_v2_5`; falls back to `say` per line on errors) when `ELEVENLABS_API_KEY` is set, else
  `MacSayTTS` (pre-spawned `say -f -` per voice, ~0.5 s per line when idle), else stub tones.
- `make dev-live` points the *fraud* analyzer at `LLM_PROVIDER=auto` (Nebius/NVIDIA with a key, else the
  keyword matcher). Pointing it at the same local Ollama serializes it with the persona LLM: measured
  +3 s per AI reply, and the fraud call timed out (3 s) on every utterance anyway.

Measured (M5, `make dev-live`, say TTS, qwen3.5:4b, whisper-large-v3-turbo), visitor end -> first AI audio
frame: typed turns 1.4-2.9 s (LLM first sentence 0.2-1.9 s + say 1.0-1.2 s); spoken turns 3.3-5.5 s from
end of speech (500 ms VAD hangover + STT 1.0-1.6 s + LLM + TTS; STT and TTS slow down while the
speaker/spoof models analyze the same moment). `STT_MODEL=mlx-community/whisper-small-mlx` and ElevenLabs
streaming are the two biggest remaining levers.
