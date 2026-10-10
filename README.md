# Baseline

> To detect what's real and fake, we must define a baseline.

A real-time co-pilot for bank call-center agents (Customer Layer track). It flags voice-clone account takeovers and customers being coached by scammers by comparing each call against three baselines: the customer's enrolled voice, what real human audio sounds like, and what legitimate requests look like.

- [docs/baseline_master_plan.md](docs/baseline_master_plan.md): plan, architecture, 18-hour schedule
- [docs/event_info.md](docs/event_info.md): hackathon theme, judging, schedule
- [docs/brain_dump.md](docs/brain_dump.md): original raw notes
- [backend/README.md](backend/README.md): pipeline, live-call API, WebSocket event contract, report shape, stub-mode sidecars

## Quickstart

Requires `uv` and Node/npm (both in `~/.local/bin` on the build Mac; the Makefile adds it to PATH).
The AI caller's LLM runs in [Ollama](https://ollama.com): `ollama pull qwen3.5:4b` and keep it running.

```bash
cp .env.example .env        # optional keys: NEBIUS_API_KEY (fraud LLM), ELEVENLABS_API_KEY (caller voice)
make setup ML=1             # uv sync --extra ml (backend, real models) + npm install (frontend)
make dev-live               # live-call backend on http://localhost:8000 (real models; second terminal for the next one)
make dev-frontend           # site on http://localhost:5173
```

Open the site, press **Take a call**, pick a side and a scenario in the lobby, and talk to the AI caller.
Baseline annotates the call live; every call ends with a report at `/report/<id>` (listed on `/reports`),
including call audio: the AI caller's voice always, the visitor's only if they tick the opt-in in the lobby.
`?mock=1` on any page runs a scripted call with no backend.

`make dev-backend` starts the same API with stub voice models (no mic transcription): fine for UI work.

### What runs where (and what costs credits)

| Part | `make dev-live` | `make dev-backend` | Cost |
|---|---|---|---|
| Speech-to-text | Whisper large-v3-turbo (MLX, local) | stub (sidecar transcripts only) | free |
| Speech detection | Silero (local) | energy threshold | free |
| Voice match | ECAPA (local) | stub | free |
| Deepfake audio | `mo-thecreator/Deepfake-audio-detection` (local) | stub | free |
| AI caller persona | Ollama `qwen3.5:4b` (local) | same | free |
| Fraud analysis | Nebius if `NEBIUS_API_KEY`, else NVIDIA, else keywords | same | **API credits** |
| Caller voice (TTS) | ElevenLabs if `ELEVENLABS_API_KEY`, else macOS `say` | same | **API credits** |

For $0 development: `TTS_PROVIDER=say` (macOS voice) and `LLM_PROVIDER=ollama` (slower) or `stub` (keywords).

Other commands:

```bash
make test                   # pytest (unit + end-to-end replay through the pipeline and the WebSocket)
make eval NOTE="what changed"   # scores data/eval/labels.csv, appends a row to results/history.csv
make clips                  # regenerate demo clips in data/demo/ with macOS `say` + ffmpeg
make enroll-demo            # demo voiceprint for CUST-004217 (dev-live runs it if missing)
make build                  # production build of the site
cd frontend && npm test     # frontend unit tests; `node scripts/live-smoke.ts` = typed call against a backend
```

## Layout

```
backend/    FastAPI app, pipeline, providers/, detectors/, fusion, caller/ (live call, persona, TTS, reports, recording)
frontend/   React + Vite + TypeScript site: landing, lobby, call room, reports; WebGL renderers in src/gl
scripts/    eval.py, make_clips.py
tests/      pytest suite (run from backend/: `uv run pytest`)
data/       demo/ (small tracked clips + sidecars), eval/ (labels.csv; audio gitignored), enroll/, reports/ and train/ (gitignored)
results/    history.csv (eval runs over time, tracked)
```

## Eval set

`data/eval/labels.csv` columns: `file,speaker,is_synthetic,is_fraud,condition,notes` (`file` relative to the
CSV). `eval.py` reports spoof accuracy (vs `is_synthetic`), fraud accuracy (vs `is_fraud`) and end-to-end
accuracy (alert >= caution vs synthetic-or-fraud), with false-alarm / miss rates and a per-condition breakdown.
