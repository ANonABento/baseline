# Baseline: Hackathon Master Plan

> *"To detect what's real and fake, we must define a baseline."*

**Event:** Building from the Farm (Stanford Founders Club × SF Tech Week 2026). **Theme:** Future of Work for Enterprise. **Track:** Customer Layer.
**Constraints:** 18-hour overnight build (Thu Oct 9, 7 PM → **submit Fri Oct 10, 9:00 AM on MentorMates**) · 1–2 builders · $0 spend (local models + sponsor credits) · must demo flawlessly · runs on a MacBook (M5, 24 GB). An RTX 5090 is a *possible* upgrade, never a dependency.

---

## 0. Event Facts That Shape the Plan

| Fact | What it means for us |
|---|---|
| Theme is **enterprise**; tracks are Digital Twin / Company Brain / **Customer Layer** | Pitch Baseline as a bank's **customer-layer** defense, not a consumer app (§1) |
| Judged on **real improvement over the build** | Log `eval.py` results with timestamps all night → show an accuracy-over-time chart in the demo |
| Judged on **quality relative to compute spent** | Our "runs on one laptop, no GPU server" story is a *strength*. Report latency + hardware. |
| Judged on **robustness to edge cases not explicitly built for** | Held-out edge-case suite (§4): unseen speakers, unseen voice types, noise, phone codec, unseen scam scripts |
| Partners: ElevenLabs, Replit, World Labs, **NVIDIA** (free credits) | ElevenLabs = test data; NVIDIA API credits = alternate LLM; Replit = public URL |
| Top 5 teams present at the final round (12–2 PM) | Need a crisp 3-min demo + a backup video recorded before 9 AM |
| Schedule: build 7 PM → 9 AM; mentors on hand 7–9 PM | Get the riskiest questions (spoof detector approach) to mentors in the first 2 hours |

> ⚠️ **Check the event Rules (Eligibility / Build sections) for whether code written before 7 PM is allowed.** Until confirmed, pre-event prep = planning, installing tools, downloading models, redeeming credits, recording voice data. No app code.

---

## 1. The Product (Customer Layer framing)

**Voice is now the weakest link in the customer relationship.** Banks, brokerages and telcos let customers authenticate and move money over the phone, and a 30-second voice clone now beats "the agent recognizes you" and many voiceprint systems. Meanwhile, their most vulnerable customers (seniors, low-income families) are being coached by scammers *while on the phone with the bank*.

**Baseline is a real-time co-pilot for the bank's call-center agent.** It already knows what each customer sounds like and how legitimate calls go, and flags in real time when a call deviates from that:

1. **Who it should be:** does this voice match the customer's enrolled voiceprint? (speaker verification)
2. **What a human sounds like:** does the audio carry synthetic / voice-changer artifacts? (spoof detection)
3. **What legitimate requests look like:** is the caller following a known fraud / social-engineering pattern (urgent wire, change of phone number/email, "my grandson needs bail," gift cards, crypto, secrecy)? (LLM + fraud playbook, with citations to bank policy / FTC guidance)
4. **The caller's own baseline (soft signal):** the first ~20 s set their normal pitch, energy and speech rate; the meter shows pressure spikes relative to that.

**Two demo scenarios, one engine:**
- **Account takeover:** a fraudster calls the bank using a voice clone of a customer and asks to change the phone number and wire funds.
- **Vulnerable customer:** a real elderly customer calls to wire money "to help my grandson." The voice is genuine, but the *script* matches a grandparent scam, so the agent is prompted to slow down and intervene. (Keeps judge feedback 1, the humanitarian angle, inside the enterprise theme.)

**The core claim: no single signal is trusted.** A voice clone can fool voice-ID; Baseline still catches it because the audio looks synthetic *and* the request matches a fraud pattern. Alerts escalate when independent signals agree.

### What we will *not* claim
- **No "lie detection."** Voice-stress lie detection has weak scientific support. We show *deviation from the speaker's own baseline*, labeled "pressure / arousal."
- **No "detects every deepfake."** We show measured accuracy on held-out data, including edge cases we didn't train on.

### Scope
- **In:** bank call-center co-pilot, audio only.
- **Out (one "future work" slide):** video deepfakes, lending/income verification, recruiting/resume fact-checking, "Company Brain" auto-updating fraud playbooks.

---

## 2. Architecture

```
 Agent dashboard (React/Vite + Tailwind)            Python backend (FastAPI)
 ┌───────────────────────────┐   16 kHz PCM    ┌──────────────────────────────────────────┐
 │ Mic (AudioWorklet)  ──────┼──── WebSocket ─▶│ Audio ingest ─▶ VAD (silero) ─▶ utterance│
 │ or Replay picker          │                 │                                    │     │
 │ Customer profile (enrolled)│                │      ┌──────────────┬──────────────┼──┐  │
 │ Live transcript           │                 │      ▼              ▼              ▼  ▼  │
 │ Trust Score               │◀── events ──────┤     STT      Speaker-verify   Spoof Prosody
 │ Signal cards + "why"      │   (same WS)     │      │         (ECAPA)       score  vs baseline
 │ Suggested agent action    │                 │      ▼                                   │
 └───────────────────────────┘                 │  LLM fraud analyzer (rolling transcript) │
                                               │      + fraud playbook (JSON, cited)      │
                                               │      ▼                                   │
                                               │  Fusion ─▶ Trust Score + reasons + action│
                                               └──────────────────────────────────────────┘
```

**Replay mode = same pipeline.** The server streams a WAV at real-time pace into the exact same ingest path as the mic. The demo never depends on a live mic working.

### Pluggable backends (the "don't over-rely on the 5090" rule)

| Stage | Default (free, runs on Mac) | Alternate (free) | 5090 upgrade |
|---|---|---|---|
| VAD | `silero-vad` (CPU) | — | — |
| STT | `mlx-whisper` (small/medium on M5 GPU) | ElevenLabs Scribe (sponsor credits) | `faster-whisper` large-v3 |
| LLM | Nebius Token Factory / NVIDIA API credits (OpenAI-compatible) | Ollama local (~8B model fits in 24 GB) | bigger local model |
| Speaker verify | SpeechBrain ECAPA-TDNN (CPU) | — | — |
| Spoof detect | Frozen SSL embeddings (WavLM/wav2vec2) + small classifier we train | pretrained HF deepfake classifier | fine-tune the SSL model |
| Prosody | `parselmouth` / `librosa` (CPU) | — | — |

### Fusion (simple and explainable)
- Each detector emits `{signal, score 0–1, confidence, reason}`.
- Trust Score = 100 − weighted risk, smoothed over time.
- **Alert levels:** 1 signal → "caution" (yellow); ≥2 independent signals → "high risk" (red card with reasons, citations, and a **suggested agent action**, e.g. "Do not process the wire. Verify by calling back on the number on file.").

---

## 3. The Spoof Detector: Make It Actually Work

The flashiest and most fragile piece. Off-the-shelf ASVspoof models often miss modern ElevenLabs voices and degrade on speaker/phone audio.

1. **Pretrained check (≤1 h):** run one pretrained HF deepfake-audio classifier on the eval set. Record the number. That's our "start" point on the improvement chart.
2. **Our own calibrated classifier (3–4 h):**
   - Frozen WavLM/wav2vec2 embeddings on ~3 s windows → logistic regression / small MLP.
   - **Real:** team recordings + public speech (LibriSpeech / Common Voice).
   - **Fake:** ElevenLabs clones of *team members only (with consent)* + ElevenLabs library voices.
   - **Hold out a whole speaker** for evaluation, or the model learns *who* instead of *real vs. fake*.
3. **Match the demo channel:** if the demo plays audio through a speaker into a mic, record some training clips that way too. Add phone-codec augmentation (resample to 8 kHz and back).

**Demo moment:** voice match passes ("a normal voiceprint system would let this through"), while the spoof detector and fraud analyzer catch it.

---

## 4. Testing & Evaluation (this is a judging criterion)

- **Eval set** in `data/eval/` + `labels.csv`: `{file, speaker, is_synthetic, is_fraud, condition, notes}`. Covers real-benign, real-fraud (vulnerable-customer script), fake-benign, fake-fraud.
- **Edge-case suite (never trained on):** a held-out speaker; a voice-changer or TTS that isn't ElevenLabs (e.g. a free local TTS); background noise; phone-codec audio; a fraud script paraphrased in a way not in the playbook; a benign call that *mentions* wires/gift cards legitimately (false-positive check).
- **`scripts/eval.py`** prints per-module accuracy + end-to-end verdicts and **appends a timestamped row to `results/history.csv`**. That file becomes the "real improvement over the build" chart.
- **Unit tests:** fusion logic; LLM output parser (malformed JSON, timeouts).
- **Demo gate:** both demo calls produce the expected verdict 5 runs in a row.

---

## 5. Demo Script (3 minutes)

1. **Hook (20 s):** the voice-clone threat to phone banking + a current FTC figure on impersonation scam losses.
2. **Setup (15 s):** agent dashboard; customer "Margaret" has an enrolled voice baseline on file.
3. **Call 1, account takeover (60 s):** clone of the customer asks to update the phone number and wire $9,000. Voice match ✓ → spoof ✗ → fraud pattern ✗ → **red alert + suggested action**.
4. **Call 2, vulnerable customer (40 s):** the real customer, genuine voice, wants to wire bail money for her "grandson." Voice ✓, spoof ✓, but the script matches a grandparent scam → agent prompted to intervene gently.
5. **Proof (35 s):** improvement chart from `history.csv`, edge-case results, "runs on one laptop" latency numbers.
6. **Close (10 s):** "To detect what's real and fake, we must define a baseline."

**Fallback ladder:** live mic → replay mode → screen-recorded video (record by ~8 AM).

---

## 6. Repo Layout

```
backend/
  app.py                  # FastAPI, WebSocket + replay endpoints
  pipeline.py             # ingest → VAD → fan-out → fusion
  providers/              # stt_*.py, llm_*.py (pluggable)
  detectors/              # speaker.py, spoof.py, prosody.py, fraud.py
  fusion.py
  kb/fraud_playbook.json  # ~30 patterns with source/policy citations
frontend/                 # React + Vite + Tailwind agent dashboard
data/  enroll/ eval/ train/   # audio (gitignored except small demo clips)
results/history.csv       # eval runs over time
scripts/  eval.py  train_spoof.py  make_clips.py
tests/
```

---

## 7. 18-Hour Build Plan

Roles if 2 people: **A = audio/ML** (VAD, STT, speaker, spoof, prosody, eval) · **B = app** (FastAPI WS, LLM fraud analyzer, playbook, fusion, frontend). Solo: A's pipeline skeleton first, then B, and use the cut list aggressively.

**Before 7 PM (allowed prep):** install `uv`, Node, Python 3.11; download models (mlx-whisper, silero, ECAPA, WavLM); redeem ElevenLabs / Nebius / NVIDIA credits; write the two demo call scripts; confirm the code rules.

| Time | A (audio/ML) | B (app) |
|---|---|---|
| 7–9 PM *(mentors here)* | Record team voices; generate ElevenLabs clones; label eval set. Ask mentors about the spoof approach. | Repo scaffold; FastAPI WS; replay streaming; frontend shell |
| 9–11 PM | VAD + STT on replay → transcript | LLM fraud analyzer + playbook → JSON + citations |
| 11 PM–1 AM | Speaker verify; pretrained spoof check; `eval.py` v1 → **first history row** | Transcript + events live in dashboard. **Milestone: end-to-end replay works.** |
| 1–4 AM | Train calibrated spoof classifier; edge-case suite | Fusion, alert levels, "why" cards, suggested actions |
| 4–6 AM | Prosody baseline; re-run eval after each change | Dashboard polish; live mic mode |
| 6–7:30 AM | **Feature freeze.** Lock demo clips; demo gate 5× | Improvement chart; README; latency numbers |
| 7:30–9 AM | Record backup video; submit on MentorMates **by 8:30** (buffer) | Rehearse the 3-min pitch |

### Cut list (drop in this order if behind)
1. Public deployment (Replit)
2. Live mic (replay-only is fine and safer)
3. Prosody / pressure meter
4. Custom spoof training (fall back to pretrained + honest framing)

**Never cut:** replay mode, the fraud analyzer with citations, the end-to-end red alert, and `history.csv`.

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| Spoof detector fails on ElevenLabs clones | Calibrated classifier on matched data (§3); held-out eval |
| Mic / venue audio issues | Replay mode through the same pipeline; backup video |
| Venue wifi / API outage | Ollama local LLM; everything else already local |
| STT feels laggy | mlx-whisper small; utterance-level (VAD) chunks |
| LLM returns non-JSON / slow | JSON mode + parser tests + retry; one call per utterance |
| Judges challenge "lie detection" | We don't claim it; deviation-from-baseline + measured accuracy |
| Running out of time at 4 AM | Feature freeze at 6 AM is non-negotiable; cut list |
| Judges see it as consumer, not enterprise | Lead with the bank call-center agent; seniors are the bank's customers |

---

## 9. Sponsor Tools (only what earns its place)

| Sponsor | Role in Baseline | Priority | Redemption |
|---|---|---|---|
| **ElevenLabs** (event partner) | Cloned/synthetic test + training audio; optional Scribe STT | Core | Discord → `#coupon-codes` → Start Redemption → SF Tech Week Hackathon at Stanford |
| **Nebius Token Factory** | Primary LLM ($100 credits) | Core | QR code / form → top up in profile with unique code |
| **NVIDIA** (event partner) | Alternate LLM via API credits; frame the 5090 as the scale-up path | Useful | Via event |
| **Replit** (event partner) | Public demo URL at the end | Optional | Promo `FUTUREOFWORKREPLIT` |
| **SharedNet** | Coordinate coding agents if 2 people run agents in parallel | Optional | `sharednet.ai` → create Room → share invite |
| **Maritime** | Backend hosting for a public URL | Optional | Promo `STANFORDFARM` at checkout on maritime.sh |
| **World Labs** (event partner) | Not used (no fit for voice security) | Skip | `SUBSCRIPTION-1-MONTH` / `30K-CREDITS-BUILD` |

**Ethics note for the pitch:** we only clone our own team's voices, with consent.
