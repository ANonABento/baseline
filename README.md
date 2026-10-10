# Baseline

> To detect what's real and fake, we must define a baseline.

Baseline builds a **trust profile for voice interactions with stakes**: a credit-score-like view of how a speaker behaves under pressure (track: "credit score for interviews"; also callers and clients, anything involving a voice and stakes). From the live voice it extracts behavioural signals (tone drift, speech rate, hesitation, de-escalation/response latency, emotion, arousal, delivery, each also as a delta vs the speaker's own baseline), says what they *could* mean with hedges and alternatives, records the speaker's operational decisions, and shows it all on a live **Digital Twin dashboard** backed by an **independently verifiable credential** (Ed25519 `did:key`, [docs/verify.html](docs/verify.html)).

**Demo:** scam-call simulation: a **human plays the scammer**, our AI pushes back and applies pressure (e.g. as the bank agent asking verification questions). The dashboard shows the scammer's signals and decisions as the call unfolds; at the end the observations are signed into a credential anyone can verify offline.

**Demo status (code audit 2026-10-10):** the live call (`/call`, "You're the scammer") currently streams the transcript, fraud-pattern, speaker and spoof notes; the behavioural signals are computed (`voice_state.py`, `session_signals.py`) but not yet shown live, and the Digital Twin page, decision tagging during the call, credential issuance from the app and the notebook model are not wired in yet (credential works as a CLI: `scripts/credential.py`). Gaps and order of work: [docs/ui_spec_signals.md](docs/ui_spec_signals.md) §9.

**Not a lie detector.** Deception is one possible reading of the signals, never a verdict; scores are uncalibrated model scores; a human decides; consent-based use only.

*Context:* the build started as a real-time co-pilot for bank call-center agents (voice-clone account takeovers, customers coached by scammers: enrolled voice, spoof detection and an LLM fraud playbook, fused). That pipeline, the quickstart and the eval set below still apply.

**Second mode: pressure simulation (Digital Twin + verifiable credential).** In the lobby choose "Pressure simulation": you are the bank agent, an AI caller applies scripted pressure (level 1 to 3), and Baseline reads **your own** delivery live (pitch, loudness, speech rate, pausing, each as change vs your first 3 turns; response latency; recovery time after your biggest change; keyword-detected decisions such as asking to verify or refusing). A live Digital Twin panel shows it during the call; at the end the report page shows the twin summary and an Ed25519 `did:key` credential that anyone can verify offline at `/verify.html`. The credential proves who signed which observations; it is **not** a measure of skill, honesty or suitability, and no signal here is calibrated against real stress or job performance (exploratory, small N). Contract and limits: [docs/ui_spec_signals.md](docs/ui_spec_signals.md), [backend/README.md](backend/README.md).

- [docs/baseline_master_plan.md](docs/baseline_master_plan.md): plan, architecture, 18-hour schedule
- [docs/finetuning_plan.md](docs/finetuning_plan.md): model plan; two-stage signal model (signals first, optional deception readings), data, evaluation, safeguards
- [docs/architecture.md](docs/architecture.md), [docs/ui_spec_signals.md](docs/ui_spec_signals.md): runtime, Digital Twin and credential contract
- [docs/train_on_gpu_machine.md](docs/train_on_gpu_machine.md): full run of `notebooks/baseline_brief_architecture.ipynb` on the RTX 5090 (done 2026-10-10; weights `data/models/baseline_brief_full.pt` via Git LFS, results `results/brief_architecture_full.json`)
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

Open http://localhost:5173/call to take a live call (roles: bank agent, scammer, pressure simulation; with no backend running the page falls back to a clearly labelled demo mode with simulated values). The original clip-replay dashboard is at `/legacy`: pick `takeover_clone.wav`, press **Start replay**: the transcript streams in real time, the fraud card flags the account-takeover script, and the alert goes red. `benign_balance.wav` stays green; `grandparent_vulnerable.wav` is caution. For real models use `make dev-live` (also turns on the WavLM emotion probe, `EMOTION_PROVIDER=wavlm`, an acted-speech probe shown as a side bar only).

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
frontend/   React + Vite + TypeScript live-call app (/call, /report/<id>, Digital Twin panel, public/verify.html); v1 Tailwind dashboard under /legacy
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

Voice and content **signal summaries**, not lie detection: the live backend has no deception or honesty output. The offline notebook model can add optional, uncalibrated bluff/fabrication readings (secondary; `docs/finetuning_plan.md`). `backend/detectors/voice_state.py` (via the `prosody` signal) reports how an utterance's pitch, loudness, speech-rate proxy and pauses **differ from the same speaker's earlier delivery** (`details.delivery_change`, 0 to 1 or null; hedged `delivery_markers`; `status` is `ok`, `building_baseline` or `insufficient_evidence`; `calibration_status` is always `not_established`). A change can come from excitement, a noisy line, a new topic or a different microphone. The score is sign-agnostic, so any direction of change raises it.

Exploratory evidence (open data only, no recordings of people; tables in `results/public_checks.md`, architecture in `docs/architecture.md`):
- Held-out people, ordinary meeting speech (AMI): the shipped rule fired on a mean 9.5% of usable utterances per speaker-meeting session (95% CI 0.7 to 22.9%, 14 sessions from 9 speaker ids; median session 0%, one session 93%).
- Acted emotion (RAVDESS, 12 held-out actors, single-clip rule): 79.9% of high-arousal clips flagged, 16.7% of held-out calm/neutral clips. Acted emotion is not real stress.
- No open dataset has stress ground truth: S2 (change vs own baseline) is an unvalidated HYPOTHESIS. Thresholds were tuned on public data through three runs, so the held-out numbers are optimistic.
- Robustness: splitting tune/report halves by meeting instead of person raised the AMI rate to 12.8% (CI 2.8 to 28.5%, 12 sessions), so 9.5% is probably optimistic. A frozen WavLM probe reaches 0.751 on acted 8-class emotion vs 0.430 for the hand-built features (not integrated).
- Spoof: see the section above (15/40 real audiobook clips falsely flagged), so spoof or prosody alone should never drive a high alert.
