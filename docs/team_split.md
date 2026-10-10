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

**Owns:**
- Backend: `backend/detectors/{speaker,spoof,prosody}.py`, `backend/segmenter.py`, `backend/providers/stt_*`, `scripts/`, `data/`, enrollment.
- Frontend: `components/SignalCards.tsx`, `CustomerPanel.tsx`, `TrustGauge.tsx`, new `ProofStrip.tsx`, new `EnrollPanel.tsx`.

**Tasks:**
1. Record both teammates' voices (~3 min natural speech + the demo scripts). Make ElevenLabs clones (team voices only, with consent).
2. Review and merge the real-models branch (mlx-whisper, silero, ECAPA enrollment, pretrained spoof).
3. Generate ~60 eval clips (real/fake × benign/fraud, using TTS *and* the voice changer) and label them in `data/eval/labels.csv`. Run `make eval` to produce the **first history row** (the pretrained baseline).
4. Signal cards for Voice Match and Synthetic Audio: real score, a one-line *why*, and evidence (similarity to the enrolled voice; fake probability per window).
5. Train the WavLM + logistic-regression spoof classifier (`scripts/train_spoof.py --holdout-speaker`). Build the edge-case suite: held-out speaker, non-ElevenLabs TTS, pitch-shift, noise, phone codec.
6. **ProofStrip:** accuracy over the night from `results/history.csv` (needs a small `GET /history` endpoint; ask C or add it), per-utterance latency, "runs on one MacBook."
7. If on track: Pressure card (prosody vs. the caller's baseline), and EnrollPanel (record 20 s → enroll a customer live).
8. **Pitch:** own the proof section; record the final demo audio + backup video.

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
