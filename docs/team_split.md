# Team Split: Two Vertical Slices

Each person owns **backend + frontend + part of the pitch** for their slice, so both of you can demo and explain your half end to end.

Tell your Claude Code session: "Read docs/team_split.md (my section) and docs/baseline_master_plan.md, then start on task 1."

## Context in 30 seconds
Baseline is a real-time co-pilot for **bank call-center agents**. It flags voice-clone account takeovers and customers being coached by scammers. We **sell to banks and protect the innocent.** The skeleton works end to end: replay or mic → pipeline → detectors → fusion → WebSocket → dashboard. Real models (STT, VAD, voice match, pretrained spoof) are being merged from a branch.

## Setup (both)
```bash
git clone https://github.com/ANonABento/baseline.git && cd baseline
# install uv: curl -LsSf https://astral.sh/uv/install.sh | sh ; Node 20+ needed
make setup && make test
cp .env.example .env              # add NEBIUS_API_KEY
make dev-backend                  # terminal 1
make dev-frontend                 # terminal 2, open the URL, pick a clip, press Start
```

## Shared rules
- **Contract:** `backend/events.py` ↔ `frontend/src/types.ts` (event schema) and `DetectorResult` in `backend/detectors/base.py`. Adding *optional* fields is fine; announce it. Renaming or removing fields requires agreement first.
- **Frontend:** one component per file in `frontend/src/components/`, each with a single owner. `App.tsx` belongs to C. V asks C to place new panels in the layout, or adds the one-line import and mount and says so.
- Each person works on their own branch and merges to `main` at every sync. Run `make test` and `npm run build` before merging.
- **Syncs:** 10:30 PM · 1 AM · 4 AM (cuts) · **6 AM feature freeze** · **submit by 8:30 AM**.

---

## V: Voice & Proof (teammate)
*"Is this the real customer, and is it a real human?"*

> **Updated ~11:30 PM:** the frontend is being redesigned as a public "try it live" site (lobby → queue → live call with an AI fraudster → call report). **V's frontend tasks are paused. Focus 100% on voice models, data and eval.** The real models (mlx-whisper, silero, ECAPA, pretrained spoof) are already merged. Don't edit `app.py`, `pipeline.py` or anything in `frontend/`: agents are building the live-call backend and the new UI there right now.

> **Model direction (2026-10-10, V):** beyond spoof/speaker, V now also builds the voice + content model described in [`finetuning_plan.md`](finetuning_plan.md) (target-specific scores, frozen pretrained encoders first, controlled-negotiation ground truth, audio-vs-text ablations). It is model side only: C owns how the application and pitch use it (human-connection story, e.g. scam prevention for elderly callers). Interface: optional `DetectorResult.details` keys, announced before merge, no renames. Scores carry `calibration_status` and are never shown as literal probabilities of lying.

**Owns:** `backend/detectors/{speaker,spoof,prosody}.py`, `backend/segmenter.py`, `backend/providers/stt_*`, `backend/ml/`, `scripts/` (except `eval_fraud.py`), `data/` (except `text_eval/`).

**Setup:** `make setup ML=1 && make enroll-demo && make test`. Weights download to `~/.cache/huggingface` (~5 GB), so start now.

**Tasks, in order:**
1. **Read `docs/research/spoof_detection.md`** (the "Do this tonight" checklist), and §3 + §10 of the master plan.
2. **Record voices (both teammates):** ~3 min of natural speech each, plus the demo lines. Make ElevenLabs clones (team voices only, with consent). Record some clips **through the demo channel** as well.
3. **Build the eval set:** real vs. ElevenLabs clone (benign + fraud scripts), plus non-ElevenLabs fakes (macOS `say`, pitch-shift) as unseen generators. Label in `data/eval/labels.csv` (`is_synthetic`, `speaker`, `expected_customer`, `is_customer`, `condition`). Run `make eval` to get the pretrained baseline row.
4. **Train the spoof classifier** with `scripts/train_spoof.py --holdout-speaker`. Per the research: pool middle WavLM layers, normalize per window, push every clip through MP3, add augmentation. Run the **shortcut audit** (silence, loudness, codec, speaker identity) so it doesn't learn the wrong thing.
5. **The live demo depends on this:** the AI fraudster speaks through **ElevenLabs TTS**, and its audio feeds straight into the pipeline as digital audio (no speaker-to-mic). Make sure the spoof detector flags ElevenLabs flash-model output reliably, and that real human mic audio (the "scammer" role, where a visitor speaks) is **not** flagged.
6. **Recalibrate speaker thresholds** on real recordings (`SPEAKER_ACCEPT_SIM` / `SPEAKER_REJECT_SIM`).
7. **Pressure meter** (prosody vs. the caller's own baseline), if time allows.
8. Run `make eval NOTE="..."` after every change, so `results/history.csv` shows improvement over the night (a judging criterion).

---

## C: Conversation & Action (Kevin)
*"What is being asked, and what should the agent do?"*

**Owns:**
- Backend: `backend/providers/llm_*`, `backend/detectors/fraud*.py`, `backend/kb/`, `backend/fusion.py`, `backend/app.py`, `backend/pipeline.py`.
- Frontend: `App.tsx` (layout), `components/Transcript.tsx`, `AlertBanner.tsx`, `CallControls.tsx`, new `Timeline.tsx`, new `FraudEvidence.tsx`, `useCall.ts`, `mic.ts`.

**Tasks:**
1. Real LLM fraud analyzer: get Nebius working (confirm the base URL + model id). Tune the prompt on `data/demo/*.txt`. Output must always parse; target under ~1.5 s per utterance.
2. New patterns (plan §1, "Borrowed from Substrata"): **verification evasion** (dodging identity questions, pushing urgency when asked to verify) and **coached customer** ("he says I need to…", "they told me not to tell you"). Add them to the playbook, the prompt and the tests.
3. **Layout pass** (a judge gets it in 5 seconds): customer left, transcript center, signals right, alert on top.
4. **Transcript + Timeline:** highlight the line that triggered each signal; clicking a flag scrolls to its line.
5. **FraudEvidence:** matched pattern, quoted line, citation link. **AlertBanner:** red takeover with the suggested agent action.
6. Fusion tuning once V's real scores arrive (weights, thresholds, so false alarms stay low on benign clips).
7. Live mic: test in Chrome and fix. Verify the playbook source URLs resolve.
8. **Pitch:** 3-minute script + ~5 slides (problem → demo → proof → who pays → close), and the MentorMates submission text (draft early).
