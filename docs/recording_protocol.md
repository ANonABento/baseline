# Recording Protocol: Voice-State Data (V)

> **NEEDS REVISION (2026-10-10).** The model target changed to joint voice+content analysis for commercial calls (`finetuning_plan.md`). Consent, safety, channels, QC and the grandparent scam scenes (C1-C4) still apply as scenarios. The **labels (§5) and session design (§4) are superseded** by the controlled-negotiation design with private cards in `finetuning_plan.md` §5-6; this file will be rewritten for the negotiation design. The application layer (elderly scam prevention, owned by C) is unchanged; the grandparent scenes remain useful as extra scenarios.

Status: **DRAFT, not yet run.** Owner: V. Supports the model in `baseline_master_plan.md` §2.5 and the demo in §5.

**Goal.** Collect consented, labeled recordings of a person (the "protected caller") speaking calmly and then under scripted, mild social pressure, so we can (1) set and test per-speaker baselines, (2) calibrate stress-related and anger-like scores, (3) validate on the demo mic and channel, and (4) record the demo clip.

**What this data can and cannot support.** It supports estimating *stress-related vocal change vs a speaker's own baseline*. It cannot support any claim about lying (we collect no deception labels), real-world distress (the pressure is staged and mild), or generalization beyond a handful of speakers. Say all three on the slide.

---

## 1. Consent and safety (do before recording anything)
- **Written consent per participant** (a short signed or typed-and-dated note in `data/train/consent/`, gitignored): what is recorded, that it is used only for this hackathon project, stays on the team's laptops, and can be deleted on request. Cloning anyone's voice (ElevenLabs) needs that person's explicit consent in the same note.
- **Adults only. Teammates and consenting volunteers only.** No recordings of strangers, customers, or real bank/scam calls.
- **Fictional persona only.** Participants never say their real account numbers, addresses, SSNs or real family details. Use the persona card (§6). No PHI/PII in files, filenames or logs.
- **Mild induction only.** Pressure is verbal urgency from a scripted caller, nothing threatening or humiliating. **Stop word: "pause".** Anyone can stop at any time with no reason. After each session, a 1-minute calm debrief and the participant confirms they feel fine.
- **No health inference.** We record no mood, depression or medical labels.
- **Storage:** raw audio in `data/train/` (gitignored), never uploaded to third parties except scripted scammer lines sent to ElevenLabs TTS (text only, no participant audio) and cloned voices created with consent. Delete on request.

## 2. People and roles
| Role | Who | Notes |
|---|---|---|
| **Protected caller** (speaker under study) | each teammate, in turn (and 1-3 volunteers if available) | plays "Margaret" or "Robert" from the persona card |
| **Pressuring caller** | the other teammate reading lines live, **or** ElevenLabs TTS of the same lines | record both versions for a few scenes: TTS is what the live demo uses |
| **Annotators** | two people who did not play the scene (cross-annotate if only two teammates; state this limitation) | blind to the scene's pressure level and to self-reports |

## 3. Equipment and channels (record all of these for a subset)
- **Primary:** the demo laptop's mic, quiet room. WAV, record at 48 kHz mono, resample to 16 kHz in ingestion.
- **Phone channel:** a phone call between two phones, recorded on the receiving side (compressed, band-limited).
- **Demo channel:** audio exactly as the live demo will deliver it (browser mic into the pipeline; scammer TTS as digital audio).
- **Room tone:** 30 s of silence per channel per session (noise augmentation and a loudness reference).
- Log per clip: device, channel, room, distance to mic, gain setting. Do not change gain mid-session.

## 4. Session structure (about 35 min per participant)
| Block | Content | Duration | Purpose |
|---|---|---|---|
| **A. Baseline** | answer neutral prompts naturally (describe your morning, a recent meal, your commute); then read 10 neutral sentences | 3 min + 1 min | per-speaker baseline, calm reference |
| **B. Calm calls** | 2 benign bank calls with a friendly pressuring caller (balance inquiry, address-update question) | 2 x 1 min | calm-in-context control |
| **C. Pressure scenes** | 4 scam scenes (§7), each with 3 escalation levels L1 to L3 | 4 x 1.5 min | the signal we want |
| **D. Recovery** | calm chat, same prompts as A | 1 min | return-to-baseline check |

Rules:
- **Randomize scene order per participant** and balance which scene comes first; do not always put the most intense scene last.
- **Improvise, do not act.** The protected caller answers as themself in the persona, in their own words, and is told *not* to perform "being stressed". Acted emotion is a known generalization problem.
- **Second session on a different day** for at least some participants, so splits can be session-disjoint.
- Breaks between scenes; the participant can skip any scene.

## 5. Labels
Collected per **segment** (VAD segment of <= 30 s), stored as in the handoff schema; `null` = not measured, never 0.

| Target | Scale | Source (`label_sources`) | When |
|---|---|---|---|
| `self_reported_stress` | 0 (completely calm) to 4 (very tense), one written question: "How tense did you feel during that scene?" | `speaker_check_in` | right after each scene, per scene (assigned to all its segments, so it is coarse; say so) |
| `perceived_anger` | 0 to 4 | `human_annotation` | two annotators listen blind to scene level and self-report; report weighted kappa |
| `perceived_stress` (optional) | 0 to 4 | `human_annotation` | same annotators, same session |
| `pressure_level` | L0 baseline, L1, L2, L3 | `scripted_condition` | known from the script; this is the experimental condition, **not** a label of inner state |

No deception label is collected or created. The agent flags explicit contradictions with stated facts from the text, never from tone.

### Metadata row (`data/train/voice_state.jsonl`)
```json
{"file_name":"audio/spk01_ses1_C2_L3_seg04.wav","speaker_id":"spk01","session_id":"spk01_ses1",
 "scene":"C2","pressure_level":"L3","caller_type":"human|elevenlabs","channel":"laptop|phone|demo",
 "start_seconds":12.0,"end_seconds":20.0,"text":"...",
 "targets":{"self_reported_stress":3,"perceived_anger":0,"perceived_stress":null},
 "label_sources":{"self_reported_stress":"speaker_check_in","perceived_anger":"human_annotation"},
 "consent_id":"spk01","split":"train|val|test"}
```
Filename: `<speaker>_<session>_<block><n>_<level>_seg<k>.wav`. Never put real names in filenames; use `spk01`.

## 6. Persona cards (fictional; keep with the scripts)
- **Margaret Chen**, 72, retired teacher, account `CUST-004217` (matches `data/enroll` demo), grandson "Danny". The pressuring-caller lines in scene C1 are the `data/demo/grandparent_vulnerable.txt` story so the recorded clip can replace the `say` voice in the demo.
- **Robert Alvarez**, 68, retired bus driver, granddaughter "Mia".
Participants may use either persona; facts are on the card so there is something concrete to contradict or confirm.

## 7. Scenes (pressuring-caller lines; L1 calm, L2 urgent, L3 insistent)
The protected caller replies freely. Pressuring caller reads the line for the current level and moves up a level after each protected-caller reply; if the participant says "pause", stop.

- **C1 Grandparent bail.** L1: "Hello, I'm calling about your grandson. He has been in an accident and needs help." L2: "He's been arrested. A lawyer needs eight thousand dollars wired today." L3: "Please, there isn't time. Don't tell anyone, he's embarrassed. The lawyer is waiting on the other line."
- **C2 Fake bank security.** L1: "This is the fraud department. We noticed unusual activity." L2: "To protect your money, move it to a safe account now." L3: "If you hang up, the account will be frozen. Do it now."
- **C3 Prize / tax.** L1: "You've been selected for a refund." L2: "We need a small fee in gift cards to release it." L3: "This offer expires in five minutes. Read me the card numbers."
- **C4 Tech support.** L1: "We detected a virus on your computer." L2: "Let me connect to fix it. Install this now." L3: "Your accounts are being emptied as we speak, hurry."
- **B1/B2 Benign.** Friendly pace, no urgency: "Can I help with your balance?" / "Is your address still the same?"
Verification questions the pressuring caller can add: "What is your date of birth?" and "What is the name of your first pet?" (persona card answers).

## 8. Quality checks (before any training or eval use)
- No clipping (peak < -1 dBFS), stable noise floor, no dropped frames, sample rate confirmed.
- Every segment has `speaker_id`, `session_id`, `consent_id`, `channel`; nulls where unmeasured.
- Annotator agreement reported (weighted kappa). If kappa < 0.4, drop `perceived_*` as a target and say so.
- **Splits by speaker AND session**; no voice in two splits. With only 2-4 speakers, we cannot do speaker-disjoint testing with useful power: use public emotion corpora (`UNVERIFIED`, see §2.5 research task) for pretraining, use our data for per-speaker baseline calibration and for demo-channel validation, and report N, per-speaker results and bootstrap CIs (resample scenes, not segments).
- **Shortcut audit:** can a model predict `pressure_level` from loudness, silence, channel or speaker identity alone? If yes, that is what it learned; fix the design.

## 9. Demo alignment (§5 of the plan)
- **Human hook:** the demo opens with Margaret's story (a real teammate, consent on file) rather than a statistic. Judges see her voice baseline, then the scam call: a rising *stress-related vocal change* meter next to the quoted lines that preceded it ("He told me not to tell anyone"), and the agent's gentle prompt: "She sounds increasingly tense. Slow down and verify before any transfer."
- **Same engine, three signals:** voice match (still her?), synthetic-voice check on the *pressuring* caller (is that TTS?), script match (grandparent pattern), plus the new stress-related change on the protected caller. Alerts still escalate only when independent signals agree.
- **The recorded C1 take (best of 3, with the participant's consent) becomes the demo clip**; keep a fallback replay file.
- Say on stage: this estimates stress-related vocal signals relative to her own voice; it is not a lie detector and not a diagnosis.

## 10. Deliverables and ownership
| Item | Owner | Done when |
|---|---|---|
| Consent notes | V + each participant | signed/dated, in `data/train/consent/` |
| Raw recordings + room tone | V | passes §8 checks |
| `voice_state.jsonl` + labels | V + annotators | schema valid, nulls masked |
| Ingestion script `scripts/ingest_voice_state.py` | V | reproducible; writes manifest with hashes and seed |
| Eval table (`results/history.csv` rows) | V | audio-only vs transcript-only vs fused vs energy-only baseline |

Open decisions for the team: who the volunteers are; whether phone-channel recording is feasible on site; whether to record ElevenLabs-voiced pressuring callers for all scenes or only C1 and C2.
