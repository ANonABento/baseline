# Baseline backend

FastAPI + asyncio pipeline: `ingest -> segmenter (VAD) -> per-utterance fan-out (STT + detectors) -> fusion -> events`.

```
app.py            HTTP + WebSocket (/health, /customer, /clips, POST /replay/{clip}, WS /ws/call)
pipeline.py       CallPipeline (one per call) + analyze_wav() offline helper used by eval/tests
segmenter.py      Segmenter interface + EnergyVAD placeholder (swap for silero-vad)
providers/        STTProvider / LLMProvider interfaces; stub STT, sidecar STT, stub LLM, OpenAI-compatible LLM
detectors/        speaker.py, spoof.py (stubs), prosody.py (energy/ZCR placeholder), fraud.py (LLM + keyword fallback)
kb/fraud_playbook.json   20 fraud / social-engineering patterns with triggers, agent actions, sources
fusion.py         Trust Score + alert levels
events.py         Pydantic event schema (the WS contract, documented in its docstring)
settings.py       pydantic-settings; env vars / .env (see ../.env.example)
```

## WebSocket contract (`ws://localhost:8000/ws/call`)

- Client sends **binary** frames of 16 kHz mono int16 little-endian PCM (live mic), or **JSON** control
  messages: `{"type":"replay","clip":"takeover_clone.wav"}`, `{"type":"start","source":"mic"}`,
  `{"type":"stop"}`, `{"type":"reset"}`, `{"type":"ping"}`.
- Server pushes JSON events: `transcript`, `signal`, `trust`, `alert`, `status`. Exact fields are in
  `events.py`. Detector `score` is **risk** in [0, 1] (higher = more suspicious); `confidence` 0 means
  "no opinion" (stubs) and is ignored by fusion.
- Replay streams the WAV as int16 PCM at real-time pace (`REPLAY_SPEED`) into the same `feed_pcm16`
  path the mic uses. `POST /replay/{clip}` triggers a replay on every connected session.

## Stub mode sidecars (until real models land)

Files next to a demo WAV in `data/demo/`:

- `<clip>.txt` **sidecar transcript**. When `STT_PROVIDER=stub` (the default) the replay path and
  `eval.py` use it as the STT output, so the fraud analyzer and dashboard work end to end. One line
  per utterance, optional start time: `[11.15] I need to wire nine thousand dollars...`. Timed lines
  are assigned to the VAD utterance they fall in; untimed lines are consumed one per utterance;
  leftovers are attached at end of call. Without a sidecar the stub STT emits a placeholder.
- `<clip>.meta.json` **stub hints** (`{"stub_hints": {"spoof": {"score": .88, "confidence": .8, "reason": "..."}}}`)
  let stub speaker/spoof/prosody detectors return demo values so the dashboard can show a full
  red alert before the real models exist. Reasons are prefixed `[stub hint]`. `eval.py` always
  ignores them. Delete them once the real detectors are in.

## Dropping in real models

- STT: implement `STTProvider.transcribe(utt)` (e.g. mlx-whisper via `asyncio.to_thread`), add a
  value to `Settings.stt_provider`, return it from `providers.make_stt`.
- VAD: implement `Segmenter.feed/flush/reset` with silero; pass it to `CallPipeline(segmenter=...)`.
- Detectors: replace the body of `analyze()` in `detectors/speaker.py` / `spoof.py` / `prosody.py`;
  keep the `DetectorResult` contract.
- LLM: set `NEBIUS_API_KEY` (+ `LLM_BASE_URL`, `LLM_MODEL`) and the OpenAI-compatible provider is used;
  any error/timeout/bad JSON falls back to the keyword matcher.
