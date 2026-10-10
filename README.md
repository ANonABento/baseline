# Baseline

> To detect what's real and fake, we must define a baseline.

A real-time co-pilot for bank call-center agents (Customer Layer track). It flags voice-clone account takeovers and customers being coached by scammers by comparing each call against three baselines: the customer's enrolled voice, what real human audio sounds like, and what legitimate requests look like.

- [docs/baseline_master_plan.md](docs/baseline_master_plan.md): plan, architecture, 18-hour schedule
- [docs/event_info.md](docs/event_info.md): hackathon theme, judging, schedule
- [docs/brain_dump.md](docs/brain_dump.md): original raw notes
- [backend/README.md](backend/README.md): pipeline, WebSocket event contract, stub-mode sidecars

## Quickstart

Requires `uv` and Node/npm (both in `~/.local/bin` on the build Mac; the Makefile adds it to PATH).

```bash
cp .env.example .env        # optional: add NEBIUS_API_KEY for the LLM fraud analyzer
make setup                  # uv sync (backend) + npm install (frontend)
make dev-backend            # FastAPI on http://localhost:8000
make dev-frontend           # dashboard on http://localhost:5173 (second terminal)
```

Open the dashboard, pick `takeover_clone.wav`, press **Start replay**: the transcript streams in real time,
the fraud card flags the account-takeover script, and the alert goes red (the spoof card uses a stub
hint until the real model lands). `benign_balance.wav` stays green; `grandparent_vulnerable.wav` is caution.

Other commands:

```bash
make test                   # pytest (unit + end-to-end replay through the pipeline and the WebSocket)
make eval NOTE="what changed"   # scores data/eval/labels.csv, appends a row to results/history.csv
make clips                  # regenerate demo clips in data/demo/ with macOS `say` + ffmpeg
make build                  # production build of the dashboard
```

## Layout

```
backend/    FastAPI app, pipeline, providers/, detectors/, fusion, kb/fraud_playbook.json
frontend/   React + Vite + TypeScript + Tailwind agent dashboard
scripts/    eval.py, make_clips.py
tests/      pytest suite (run from backend/: `uv run pytest`)
data/       demo/ (small tracked clips + sidecars), eval/ (labels.csv; audio gitignored), enroll/, train/ (gitignored)
results/    history.csv (eval runs over time, tracked)
```

## Eval set

`data/eval/labels.csv` columns: `file,speaker,is_synthetic,is_fraud,condition,notes` (`file` relative to the
CSV). `eval.py` reports spoof accuracy (vs `is_synthetic`), fraud accuracy (vs `is_fraud`) and end-to-end
accuracy (alert >= caution vs synthetic-or-fraud), with false-alarm / miss rates and a per-condition breakdown.
