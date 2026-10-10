# Recording Protocol: Controlled Conversations (V)

Status: **DRAFT v2, not yet run, compliance review pending (CP1).** Owner: V. Rewritten 2026-10-10 for the model in [`finetuning_plan.md`](finetuning_plan.md) (voice and content signal summaries, **no lie detection**). The application story (elderly scam prevention, owned by C) is unchanged; its scenes are kept in §6.

**Goal.** Collect consented recordings of people speaking calmly and then under scripted conditions, so we can (1) set and test per-speaker baselines, (2) test whether stress-related change, delivery markers and emotion estimates **move in the expected direction under the conditions**, (3) validate on the demo mic and channel, and (4) record the demo clip.

**What this data can and cannot support.** It supports checking whether signals change under *instructed* conditions, per speaker. It does **not** support any claim about lying (we collect no deception labels and train no honesty output), about real distress (pressure is staged and mild), or about generalisation beyond a handful of speakers. Say all three on the slide.

---

## 1. Consent and safety (before recording anything)
- **Written consent per participant** (signed or typed-and-dated note in `data/train/consent/`, gitignored): what is recorded, that it is used only for this hackathon project, stays on the team's laptops, and is deleted on request. Cloning anyone's voice (ElevenLabs) needs that person's explicit consent in the same note. **Retention period is a team decision (proposal: delete 30 days after the event); write the chosen value in the note.**
- **Adults only.** Teammates and consenting volunteers. No strangers, customers, or real bank or scam calls.
- **Fictional persona only.** No real account numbers, addresses, SSNs or family details. No PII in files, filenames or logs; use `spk01` style IDs.
- **Mild conditions only.** Verbal time pressure or a surprise question, nothing threatening or humiliating. **Stop word: "pause"**, any time, no reason needed. 1-minute calm debrief after each session; participant confirms they feel fine.
- **No health inference.** We record no mood, depression or medical labels.
- **Storage:** raw audio in `data/train/` (gitignored). Nothing leaves the team's laptops except scripted scammer *text* sent to ElevenLabs TTS (no participant audio) and clones made with consent. Uploading any participant audio anywhere needs a human decision.
- **Debrief on purpose.** Participants are told the conditions after the session. Nobody is deceived about being recorded.

## 2. People and roles
| Role | Who | Notes |
|---|---|---|
| Speaker under study | each teammate, then any volunteers | speaks as the persona, in their own words |
| Interlocutor | the other teammate, reading prompts live, or ElevenLabs TTS reading the same lines | record both versions for a few scenes; TTS is what the live demo uses |
| Annotators | two people who did not play the scene | blind to condition; labels in §4 |

## 3. Session structure (about 30 min per speaker)
| Block | Content | Time | Purpose |
|---|---|---|---|
| A. Baseline | answer neutral prompts naturally (morning, a meal, commute), then read 10 neutral sentences | 4 min | per-speaker baseline, calm reference |
| B. Spontaneous vs read | answer 4 questions in own words; then read the same answers from a prepared card | 4 min | do read-like markers separate script from spontaneous? |
| C. Conditions | 3 scenes; each runs calm, then rising time pressure, then one surprise follow-up (§6) | 3 x 3 min | do stress-related change and delivery markers move? |
| D. Fact-sheet scene | speaker has a short fact sheet; some questions fall outside it | 3 min | content observations (responsiveness, inconsistencies) |
| E. Recovery | calm chat, same prompts as A | 1 min | return to baseline |

Rules: randomise scene order per speaker; **improvise, do not act** (speaker is told not to perform "being stressed", acted emotion generalises poorly); a second session on another day for at least some speakers so splits can be session-disjoint; breaks between scenes; any scene can be skipped.

## 4. Labels
Per **segment** (VAD segment up to 30 s). `null` means not measured, never 0.

| Field | Scale | Source | Notes |
|---|---|---|---|
| `condition` | baseline, pressure_L1..L3, surprise_followup, read_script, spontaneous, in_fact_sheet, outside_fact_sheet | `scripted_condition` | the **experimental manipulation**, not an inner state and not a deception label |
| `self_reported_stress` | 0 to 4 | `speaker_check_in` | one question after each scene, coarse (per scene) |
| `perceived_emotion` / `perceived_arousal` | category / 0 to 4 | `human_annotation` | two blind annotators; report weighted kappa; drop a label with kappa < 0.4 |
| `delivery_mode` | spontaneous, read_like, unknown | `human_annotation` | independent of anything about honesty |
| `answer_responsiveness` | addresses, partial, does_not_address, unknown | `human_annotation` | |

No deception, bluff or fabrication label is collected or created.

### Metadata row (`data/train/voice_state.jsonl`)
```json
{"file_name":"audio/spk01_ses1_C2_L3_seg04.wav","speaker_id":"spk01","session_id":"spk01_ses1",
 "scene":"C2","condition":"pressure_L3","interlocutor":"human|elevenlabs","channel":"laptop|phone|demo",
 "start_seconds":12.0,"end_seconds":20.0,"text":"...",
 "targets":{"self_reported_stress":3,"perceived_arousal":null,"delivery_mode":null},
 "label_sources":{"self_reported_stress":"speaker_check_in"},
 "consent_id":"spk01","split":"train|val|test"}
```
Filename: `<speaker>_<session>_<scene>_<condition>_seg<k>.wav`.

## 5. Equipment and channels
- **Primary:** demo laptop mic, quiet room, 48 kHz mono WAV, resampled to 16 kHz in ingestion.
- **Phone channel:** call between two phones, recorded on the receiving side (compressed, band-limited), for a subset.
- **Demo channel:** audio exactly as the live demo delivers it (browser mic into the pipeline; scammer TTS as digital audio).
- **Room tone:** 30 s of silence per channel per session.
- Log per clip: device, channel, room, mic distance, gain. Do not change gain mid-session.

## 6. Scenes and the demo story
Scenes C1 to C4 use the scammer lines at three levels (L1 calm, L2 urgent, L3 insistent); the speaker replies freely and the interlocutor moves up a level after each reply.
- **C1 Grandparent bail.** L1 "Hello, I'm calling about your grandson. He has been in an accident and needs help." L2 "He's been arrested. A lawyer needs eight thousand dollars wired today." L3 "Please, there isn't time. Don't tell anyone, he's embarrassed. The lawyer is waiting on the other line."
- **C2 Fake bank security.** L1 "This is the fraud department. We noticed unusual activity." L2 "To protect your money, move it to a safe account now." L3 "If you hang up, the account will be frozen. Do it now."
- **C3 Prize or tax.** L1 "You've been selected for a refund." L2 "We need a small fee in gift cards to release it." L3 "This offer expires in five minutes. Read me the card numbers."
- **B Benign.** Friendly pace, no urgency ("Can I help with your balance?").
Fictional personas: **Margaret Chen**, 72, retired teacher, `CUST-004217`, grandson "Danny" (matches `data/enroll` and `data/demo/grandparent_vulnerable.txt`); **Robert Alvarez**, 68, retired bus driver, granddaughter "Mia".

**Demo alignment (C owns the story).** The best consented take of C1 can replace the `say` voice in the demo; keep a fallback replay. On stage: the model summarises voice and content signals relative to her own voice; it is not a lie detector and not a diagnosis.

## 7. Quality checks (before any training or eval use)
- No clipping (peak below -1 dBFS), stable noise floor, no dropped frames, sample rate confirmed.
- Every segment has `speaker_id`, `session_id`, `consent_id`, `channel`.
- **Splits by speaker and session**, no voice in two splits. With 2 to 4 speakers we cannot do a validated held-out-speaker test: use these recordings for baseline calibration, manipulation checks and demo-channel validation; report N, per-speaker results and bootstrap CIs (resample scenes, not segments).
- **Shortcut audit:** can loudness, silence, channel or speaker identity alone predict the condition? If yes, that is what a model would learn; fix the design.

## 8. Deliverables
| Item | Owner | Done when |
|---|---|---|
| Consent notes | V + each participant | signed and dated in `data/train/consent/` |
| Raw recordings + room tone | V | pass §7 |
| `voice_state.jsonl` + labels | V + annotators | schema valid, nulls masked |
| `scripts/ingest_voice_state.py` | V | reproducible; manifest with hashes and seed |
| Manipulation-check table and eval rows | V | `results/history.csv`, N and per-speaker numbers |

Open decisions for the team: volunteers; retention period; whether phone-channel recording is feasible on site; ElevenLabs-voiced interlocutor for all scenes or only C1 and C2.
