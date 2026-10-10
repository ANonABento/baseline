# Baseline

> To detect what's real and fake, we must define a baseline.

A real-time co-pilot for bank call-center agents (Customer Layer track). It flags voice-clone account takeovers and customers being coached by scammers by comparing each call against three baselines: the customer's enrolled voice, what real human audio sounds like, and what legitimate requests look like.

- [docs/baseline_master_plan.md](docs/baseline_master_plan.md): plan, architecture, 18-hour schedule
- [docs/finetuning_plan.md](docs/finetuning_plan.md): voice + content signal-summary model plan (emotion/delivery observations, no lie detection; checkpoints, data, evaluation); model side only
- [docs/recording_protocol.md](docs/recording_protocol.md): consent, safety and recording protocol for model data (draft, being revised)
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
scripts/    eval.py, make_clips.py, build_eval_set.py (real vs synthetic spoof eval set), train_spoof.py, enroll.py
tests/      pytest suite (run from backend/: `uv run pytest`)
data/       demo/ (small tracked clips + sidecars), eval/ (labels.csv; audio gitignored), enroll/, train/ (gitignored)
results/    history.csv (eval runs over time, tracked)
```

## Eval set

`data/eval/labels.csv` columns: `file,speaker,is_synthetic,is_fraud,condition,notes` (`file` relative to the
CSV). `eval.py` reports spoof accuracy (vs `is_synthetic`), fraud accuracy (vs `is_fraud`) and end-to-end
accuracy (alert >= caution vs synthetic-or-fraud), with false-alarm / miss rates and a per-condition breakdown.

### Spoof eval set (`data/eval/labels_spoof.csv`)

Built by `scripts/build_eval_set.py` (seeded; manifest in `data/eval/spoof/MANIFEST.json`): 40 real LibriSpeech
test-clean clips (CC BY 4.0, speaker-disjoint, read audiobook speech) vs 40 macOS `say` and 40 pitch-shifted fakes.
Needs `data/external/LibriSpeech/test-clean` (download from openslr.org, gitignored). Run with real providers:
`SPOOF_PROVIDER=pretrained VAD_PROVIDER=silero SPEAKER_PROVIDER=ecapa STT_PROVIDER=stub LLM_PROVIDER=stub uv run --project backend --extra ml python scripts/eval.py --labels data/eval/labels_spoof.csv --note "..."`.
First result (exploratory): the pretrained detector flags 40/40 `say` and 40/40 pitch-shifted fakes but also 15/40 real
human clips (37.5%). The end-to-end false-alarm column is confounded by the speaker module on this set; read `p_fake`.
With 16 ElevenLabs `eleven_flash_v2_5` clips (4 stock voices, same transcripts; `scripts/make_elevenlabs_clips.py`) the spoof detector flags 12/16 (Wilson 95% CI 0.51 to 0.90). No real microphone or phone audio has been tested, so this does **not** show the live demo works and does not show real human mic audio is safe from false flags.

## Voice-state signal and its limits (model side)

Voice and content **signal summaries**, not lie detection: there is no deception or honesty output and none will be added. `backend/detectors/voice_state.py` (via the `prosody` signal) reports how an utterance's pitch, loudness, speech-rate proxy and pauses **differ from the same speaker's earlier delivery** (`details.delivery_change`, 0 to 1 or null; hedged `delivery_markers`; `status` is `ok`, `building_baseline` or `insufficient_evidence`; `calibration_status` is always `not_established`). A change can come from excitement, a noisy line, a new topic or a different microphone. The score is sign-agnostic, so any direction of change raises it.

Exploratory evidence (open data only, no recordings of people; tables in `results/public_checks.md`, architecture in `docs/architecture.md`):
- Held-out people, ordinary meeting speech (AMI): the shipped rule fired on a mean 9.5% of usable utterances per speaker-meeting session (95% CI 0.7 to 22.9%, 14 sessions from 9 speaker ids; median session 0%, one session 93%).
- Acted emotion (RAVDESS, 12 held-out actors, single-clip rule): 79.9% of high-arousal clips flagged, 16.7% of held-out calm/neutral clips. Acted emotion is not real stress.
- No open dataset has stress ground truth: S2 (change vs own baseline) is an unvalidated HYPOTHESIS. Thresholds were tuned on public data through three runs, so the held-out numbers are optimistic.
- Robustness: splitting tune/report halves by meeting instead of person raised the AMI rate to 12.8% (CI 2.8 to 28.5%, 12 sessions), so 9.5% is probably optimistic. A frozen WavLM probe reaches 0.751 on acted 8-class emotion vs 0.430 for the hand-built features (not integrated).
- Spoof: see the section above (15/40 real audiobook clips falsely flagged), so spoof or prosody alone should never drive a high alert.
