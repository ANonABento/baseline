# Architecture: how everything fits (V model side + C application side)

Status 2026-10-10. Written by V (Dae's session). C-owned parts are described from reading the code, not from C. Progress and checkpoint results: [`workplan.md`](workplan.md). Model design and evidence limits: [`finetuning_plan.md`](finetuning_plan.md).

**Framing.** Baseline produces *voice and content signal summaries* with hedged notes. It makes **no lie or deception claim** and has no honesty output. The application story (protecting people such as elderly callers from scams, human connection) belongs to C.

## 1. Runtime data flow

```
mic / replayed WAV (16 kHz mono)
        │  app.py WebSocket /ws/call            (C)
        ▼
 pipeline.py  CallPipeline                      (C)
        │  segmenter.py: VAD -> Utterance        (V)  EnergyVAD | SileroVAD
        ▼
 per utterance, concurrently
   ├─ STT provider  (providers/stt_*)            (V)  mlx-whisper | stub sidecar
   ├─ speaker.py    ECAPA voice match            (V)  signal "speaker"
   ├─ spoof.py      pretrained synthetic-voice   (V)  signal "spoof"
   ├─ prosody.py -> voice_state.py               (V)  signal "prosody"  <- new this session
   └─ after STT: fraud.py (LLM + rules, kb/)     (C)  signal "fraud"
        ▼
 events.py DetectorResult {signal, score, confidence, reason, details}   (C schema)
        ▼
 fusion.py  noisy-OR of score x confidence x weight -> Trust Score,
            alert level, reasons, action                                   (C)
        ▼
 frontend (React): transcript, trust, alert, panels                        (C)
```

Rules that keep V and C decoupled:
- The only interface is `DetectorResult` in `backend/events.py`. V adds only optional keys inside `details`; nothing is renamed or removed. `SignalName` (`speaker|spoof|prosody|fraud`) is C's file, so the voice-state output rides on the existing `prosody` signal instead of a new one.
- Fusion reads only `score` and `confidence` of `prosody` (weight 0.3, soft: it can raise a caution but never a "high" alert alone; `tests/test_fusion.py::test_prosody_alone_never_high`).
- `confidence = 0` means fusion ignores the result. Poor audio and the baseline-building phase use that.

## 2. The voice-state module (V, new)

`backend/detectors/voice_state.py` (pure functions + `SpeakerBaseline`) and `backend/detectors/prosody.py` (pipeline adapter).

| Step | What it does | Where |
|---|---|---|
| Features | median pitch and pitch spread (semitones, `librosa.yin`), mean active-frame loudness (relative dBFS), energy-peak rate (a rough syllable-rate proxy, not words per minute), pause fraction | `extract_features` |
| Quality gate | under 1 s, clipped (>1% of samples), SNR proxy under 10 dB, too little voiced speech -> `insufficient_evidence`, `confidence = 0`, never joins the baseline | `quality_problems` |
| Baseline | first 3 usable utterances of this call and speaker; robust centre and spread (median, MAD) with per-feature floors; frozen once ready so a pressure run cannot drag it along | `SpeakerBaseline` |
| Change rule | a feature counts when abs(z) >= 2.5; at least 2 features together; reported only after 3 consecutive utterances (sustained); score maps the largest abs(z) to 0..1 | `assess` |
| Output | `details`: `status`, `stress_related_change` (0..1 or null), `delivery_markers` (hedged strings, e.g. "higher pitch than this speaker's earlier delivery"), `emotion_estimate` (null for now), `calibration_status = not_established`, `z`, `features` | `assess` |

What it is not: no deception key exists or will be added; the numbers are changes relative to the speaker's own earlier delivery, which can come from excitement, a noisy line, a new topic or a different microphone. **Calibration against real stress is not established** (no open dataset has stress ground truth), so S2 stays a `HYPOTHESIS`.

Not built (cut, with reason): response latency (needs both speakers' timing from C's pipeline), emotion estimate S1 (needs an encoder probe, workplan 2.2), content observations S4 (C).

## 3. Data and evaluation

| Piece | Where | Notes |
|---|---|---|
| Open datasets (gitignored) | `data/external/` via `scripts/fetch_open_data.py` (md5/sha256 manifests) | AMI ihm subset (3 shards, 7,788 segments, 6.2 h), RAVDESS (1,440 clips), LibriSpeech test-clean |
| Licence register | [`licences.md`](licences.md) | research-only, hackathon scope; RAVDESS and CREMA-D marked non-shippable |
| Public checks | `scripts/public_checks.py` -> `results/public_checks.json` | exploratory; seed 0; bootstrap CIs resample speakers/actors |
| Unit tests | `tests/test_voice_state.py` (11 cases from 8 test functions), full suite via `make test ML=1` | software correctness only |
| Spoof/speaker/e2e eval | `scripts/eval.py` -> `results/history.csv` | existing |
| Demo audio | `data/demo/` (TTS, three clips tracked) | no participant voices |

No recordings of people are made (decision 2026-10-10).

## 4. Ownership

| Area | Owner | Files |
|---|---|---|
| Voice and model side | V (Dae) | `backend/detectors/{speaker,spoof,prosody,voice_state}.py`, `segmenter.py`, `providers/stt_*`, `ml/`, `scripts/` (not `eval_fraud.py`), `data/` (not `text_eval/`), `tests/test_voice_state.py`, `docs/{finetuning_plan,licences,workplan,architecture}.md`, `docs/research/` |
| Application, content, UI, pitch | C (Kevin) | `events.py`, `fusion.py`, `pipeline.py`, `app.py`, `fraud*.py`, `kb/`, `providers/llm_*`, `frontend/` |

## 5. Evidence so far (exploratory; details in `results/public_checks.md`)
On the held-out half the change rule flags 9.5% of ordinary AMI utterances (CI 0.7 to 22.9%) and 79.9% of acted high-arousal RAVDESS clips (held-out calm/neutral: 16.7%). That shows the signal moves with acted arousal; it does not show it tracks real stress.

## 6. Open interface items (waiting on C)
0.4 accept the output contract, 0.5 which `details` keys `fusion.py` may read, 0.6 demo persona and clip source. Posted in the room; no reply as of the last read (sequence 14). Until C replies, the keys in section 2 are a **proposal**.
