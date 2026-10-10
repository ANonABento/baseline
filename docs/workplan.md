# Work Plan: V (Dae) and C (Kevin), with 3 checkpoints

Status: **PROPOSAL from V, not yet accepted by C.** Times are from `team_split.md` syncs (4 AM cuts, 6 AM feature freeze, submit 8:30 AM) and assume the plan is accepted by ~2 AM on 2026-10-10. Anything not done by a checkpoint is cut, not carried.

**Product frame (unchanged, C's):** a human-connection story, e.g. protecting an elderly caller from a scam. **Model frame (V's):** voice and content signal summaries with hedged notes, **no lie detection**, no deception score. See `finetuning_plan.md`.

**Checkpoint policy (from the coordinator, 2026-10-10):** only 3 checkpoints. QA runs at checkpoints, never on drafts or docs-only edits. A review is not re-run unless its content changed. Outward actions (uploads, posting, recordings of people, ElevenLabs clones) need a human decision.

## Who does what (roughly equal, about 6 to 7 focused hours each)
| Area | V (Dae) | C (Kevin) |
|---|---|---|
| Model signals | prosody vs own baseline, delivery markers, emotion estimate, spoof/speaker recalibration | consumes them |
| Content | spec for S4 (responsiveness, contradiction as inconsistency) | LLM prompt and tests for S4, fraud patterns |
| Data | consent, recordings, ElevenLabs clones, eval rows | demo story script and persona lines |
| Interface | optional `DetectorResult.details` keys | `events.py`, `fusion.py`, `types.ts`, panel |
| Product | eval table, honest limits slide | UI, hint wording, alert, pitch script |
| QA | `/code-qa` on V files | `/code-qa` on C files |

## Phase 0 to CP1: plan freeze (target 2:00 AM)
| # | Owner | Task | Done when |
|---|---|---|---|
| 0.1 | V | Evidence check of the interpretation table and licences: `docs/research/voice_signal_evidence.md` | file exists; every row SUPPORTED/PARTLY/UNSUPPORTED/UNVERIFIED with a source |
| 0.2 | V | Fold the verdicts into `finetuning_plan.md` §2 (drop or reword unsupported rows) | no row stays unlabelled |
| 0.3 | V | Recording protocol: **retired** (decision: open data only, no self-recorded training data) | banner on file |
| 0.4 | C | Reply in the room: accept or change the output contract (plan §9) and say where in the UI the notes show | message in room |
| 0.5 | C | Tell V which `details` keys `fusion.py` may read and whether `events.py` gets an optional field | keys listed in `docs/workplan.md` §Contract |
| 0.6 | C | Demo persona and clip source (text-to-speech or public audio; no participant voices) | named in this file |

**CP1 checks (T0 first):** `scripts/validate.sh` (outer repo) is not applicable; run `make test` in `baseline/`. Then `hallucination-detector` once on `finetuning_plan.md` and the evidence file, then `compliance-reviewer` once on `recording_protocol.md` and the licence table. **Human sign-off by both of you** on the contract before any code that depends on it.

### CP1 result (V side, 2026-10-10)
- `make test`: 193 passed. Evidence check done (`research/voice_signal_evidence.md`); hallucination-detector found no invented citations, 1 wrong section ref, 1 wrong statistic name, 1 unsourced latency claim: all fixed.
- compliance-reviewer: **NO-GO for recording** until (1) consent form wording approved by a human, (2) retention value chosen, (3) handling rules (done in protocol §1). Teammates only until a human decides on outside volunteers and jurisdiction.
- Still open: C's answers to 0.4 to 0.6; human read of the emotion2vec and WavLM licence files.

## Phase 1 to CP2: build and integrate (2:00 to 4:00 AM, cuts at 4 AM)
| # | Owner | Task | Done when |
|---|---|---|---|
| 1.1 | V | `backend/detectors/voice_state.py` (new, V-owned): per-speaker rolling baseline of pitch, energy, rate, pauses, latency; z-scores; sustained-change rule; `insufficient_evidence` when under ~1 s, clipped or noisy | unit tests pass on synthetic clips; returns `details` keys in the agreed contract |
| 1.2 | V | Spoof rerun with ElevenLabs flash output (needs the team key from a private channel, never git; synthetic voice, not a person's clone); check real human mic is not flagged; row in `results/history.csv` | row added with the note and N |
| 1.3 | V | Download open data: LibriSpeech dev/test subset, AMI subset (a few speakers, a few hours), CREMA-D or RAVDESS; write `scripts/fetch_open_data.py` with md5/sha checks | files in `data/external/` (gitignored), licence note in `docs/licences.md` |
| 1.4 | V | Public-data checks (plan §8): S1 vs emotion labels (held-out actors), S3 read vs spontaneous, S2 within-speaker variation; exploratory, N stated | table in `results/` |
| 1.5 | C | `fusion.py` and panel read the optional keys; observations and notes shown with "can reflect other causes" wording | demo clip shows the panel |
| 1.6 | C | S4 content observations via the LLM (responsiveness, contradiction flagged as inconsistency), quotes checked against the transcript | tests on `data/demo/*.txt` |
| 1.7 | C | Elderly-story demo script and persona lines (uses `data/demo/grandparent_vulnerable.txt`) | script file |

**CP2 checks (once, at about 4 AM):** `pytest` and `npm run build`; `/code-qa` once over V and C code; `/known-answer-test` on the voice_state z-score step; `/repro-check` only for numbers that go in the pitch. Cut anything that fails; do not start new features after this point.

## Phase 2 to CP3: tune, record the demo, write the claims (4:00 to 6:00 AM, freeze at 6 AM)
| # | Owner | Task | Done when |
|---|---|---|---|
| 2.1 | V | Tune thresholds on the recorded clips; false alarms on calm and on honest-but-anxious speech reported | `results/history.csv` rows |
| 2.2 | V | Optional: frozen WavLM or emotion2vec probe vs prosody z-scores; ship the simpler one if equal | one table, N stated |
| 2.3 | V | Demo audio without participants: TTS voices and a public-audio fallback replay in `data/demo/` | files, licence noted |
| 2.4 | V | README: honest limits and the eval table | README section |
| 2.5 | C | Tune fusion weights so benign clips stay quiet; alert wording | tests pass |
| 2.6 | C | 3-minute pitch script and 5 slides with the human story and the limits | files |
| 2.7 | C | Submission text draft | file |

**CP3 checks (once, at 6 AM freeze):** `/claim-audit` on README and pitch claims; `hallucination-detector` on pitch text and numbers only if they changed since CP1; one `skeptical-reviewer` pass on frozen outputs. Say "voice and content signal summaries", never "lie detection".

## 6:00 to 8:30 AM
Rehearse, record the fallback replay, final commit and push, submit. Only bug fixes after freeze.

## Contract (C fills in at 0.5)
Keys V will put in `DetectorResult.details` (proposal, not agreed): `stress_related_change` (float vs own baseline, or null), `delivery_markers` (list of strings), `emotion_estimate` (dict), `status` (`ok` or `insufficient_evidence`), `calibration_status` (`not_established`). No deception or honesty key will ever be added.

## Risks
- Few speakers and staged pressure: results are exploratory and say so.
- The spoof detector flags 15/40 real LibriSpeech clips; do not let spoof alone drive a high alert.
- Interpretation notes are only as strong as the evidence file allows.
- No recordings of people are made (decision 2026-10-10). Open datasets are acted or confounded; S2 is unvalidated.
