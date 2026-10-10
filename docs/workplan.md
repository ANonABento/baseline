# Work Plan: V (Dae) and C (Kevin), with 3 checkpoints

Status: **PROPOSAL from V, not yet accepted by C** (V side executed through CP2, see Progress below). Times are from `team_split.md` syncs (4 AM cuts, 6 AM feature freeze, submit 8:30 AM) and assume the plan is accepted by ~2 AM on 2026-10-10. Anything not done by a checkpoint is cut, not carried.

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

## Progress (V side, 2026-10-10, updated at CP2)
| # | Status | Evidence |
|---|---|---|
| 0.1 / 0.2 | done | `research/voice_signal_evidence.md`; plan §2 labelled |
| 0.3 | retired | recording protocol banner (open data only) |
| 0.4 / 0.5 / 0.6 | **OPEN, waiting on C**; no reply in the room; Kevin's session is usage-limited until 02:50 (per Dae), so not before then | proposal in section Contract |
| 1.1 | done | `detectors/voice_state.py`, `prosody.py` adapter; 160 passed, 44 skipped, 204 collected (`make test ML=1`) |
| 1.2 | done (small N) | `scripts/make_elevenlabs_clips.py`; 16 `eleven_flash_v2_5` clips, 4 premade voices (synthetic, no clone), LibriSpeech transcripts; spoof detector alone flags **12 of 16** (75%), misses 4. Same run: real LibriSpeech flagged **15 of 40** (37.5% false positive), macOS `say` 40/40, pitch-shifted 40/40. No real microphone audio exists (no recordings), so "real human mic not flagged" is NOT tested; LibriSpeech is a proxy. The `history.csv` row (2026-10-10T01:50:33) shows e2e false alarm 100% because the speaker module flags every LibriSpeech voice as not the default customer: an eval artifact, use the spoof column. |
| 1.3 | done | `scripts/fetch_open_data.py`; AMI 6.2 h subset, RAVDESS md5-verified, LibriSpeech test-clean; `licences.md` |
| 1.4 | done (exploratory) | `results/public_checks.md`, `results/public_checks.json` |
| 2.1 | done (exploratory) | `scripts/tune_voice_state.py`, `results/tune_voice_state.json`; defaults changed after an earlier run (output overwritten, so the 55% figure is UNVERIFIED from files; nearest recorded grid row z=2, baseline 3, 1 feature, sustain 2: 57% on the tune half) |
| 2.2 | not started | optional encoder probe |
| 2.3 | open | demo audio from TTS depends on C's 0.6 |
| 2.4 | partly | `architecture.md`, `results/public_checks.md`; README limits section not written (C-adjacent file) |

**CP2 result (V side):** tests 160 passed, 44 skipped (log: `results/test_log_2026-10-10.txt`; the CP1 count of 193 was `make test` without `ML=1`; software passing, not science verified). Coordinator plan followed: `/code-qa` run once (`docs/reviews/code_qa_voice_state_2026-10-10.md`); fixed NaN/inf and empty-audio handling, moved pitch tracking off the event loop, split AMI tune/report by person, added provenance to the tuning output. Known gaps from that review, not fixed: RAVDESS rows skip the quality gate; AMI revision is not pinned; LibriSpeech has no fetch command; no test that state resets between calls. Deferred to CP3 by the coordinator: `/claim-audit`, skeptical-reviewer. `/known-answer-test`: the z-score known-answer unit test (`test_zscore_known_answer`) stands in for it.
