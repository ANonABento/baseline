# Fine-Tuning Plan: Joint Voice + Content Analysis for Commercial Calls

Status: **PLAN, nothing trained.** Owner: V. Date: 2026-10-10. Source brief: `claude_voice_content_finetuning_brief.md` (user-supplied; it supersedes the earlier handoff, so §2.5 of `baseline_master_plan.md` and the label parts of `recording_protocol.md` are being updated to match).

Labels used below: **VERIFIED** = read on the model card/page this session (URL in §10). **UNVERIFIED** = from memory or not stated on the page; check before relying on it. All model outputs are `PREDICTION`s until tested on held-out data.

## 1. Scope and non-negotiables (from the brief)
- **Model side only.** The brief's commercial scenarios (sales, negotiation, bluffing) are *examples* used to define targets and controlled ground truth. The application and pitch layer is owned by slice C and stays human-connection oriented (e.g. scam prevention for elderly callers). Consent-based conversations only. Not for candidate ranking, hiring, or biometric emotion screening.
- Fine-tune pretrained models; no foundation model from scratch. A new task head is fine.
- Voice is central: keep the waveform and use learned acoustic embeddings. Text is complementary evidence.
- Analyze trajectories across the call, not isolated lines.
- Keep **observations**, **model interpretations** and **verified facts** separate in every output.
- A deception score is in scope but **target-specific**. Before calibration is established, outputs are "model scores", never "X% chance he is lying".
- Distinct targets, never collapsed: low purchase intent, uncertainty, rehearsal, bluffing, fabrication, intentional falsehood.

## 2. Targets, heads and what each means
| # | Target | Meaning | Ground truth | Notes |
|---|---|---|---|---|
| T1 | `negotiating_bluff` | speaker presents a negotiable constraint as fixed | seller's private card says the limit is flexible, yet speaker states it as fixed | seller role |
| T2 | `fabrication` | answer asserts facts not supported by the speaker's fact sheet | fact sheet vs answer, annotated | needs "don't know" as the honest option |
| T3 | `interest_intent_mismatch` | expressed interest vs verified private intent | buyer's private card (assigned intent) and a post-call commitment | buyer role |
| T4 | `read_or_rehearsed_delivery` | delivery resembles reading/rehearsal | speaker was given a script to read vs speaking spontaneously | **not** a deception label |
| T5 | `emotion` | perceived emotion and arousal/valence/dominance over time | annotators; speaker self-report kept separate | feeds the others |
| T6 | `delivery_change` | within-speaker change vs own earlier delivery, persistence and recovery | computed, plus annotation | trajectory feature |

**Overall deception score:** not built in v1. Allowed later only if its target and aggregation are defined and validated. Never an average of T1-T3.

## 3. Pretrained checkpoints
| Role | Candidate | Verified facts | Open questions |
|---|---|---|---|
| ASR + timestamps | `openai/whisper-large-v3-turbo` (already in the repo via mlx-whisper) | MIT licence; 30 s receptive field, chunked for longer audio; sentence and word timestamps (`return_timestamps`); 809M params; pruned decoder (32 to 4 layers), "minor quality degradation" | none for the hackathon |
| Audio encoder A | `microsoft/wavlm-base-plus` | 16 kHz input; pretrained on 94k h (Libri-Light, GigaSpeech, VoxPopuli); English; no tokenizer; needs fine-tuning for downstream tasks | licence is linked to a LICENSE file, **terms UNVERIFIED** |
| Audio encoder B (emotion-pretrained) | `emotion2vec/emotion2vec_plus_large` | 16 kHz; ~300M params; labels: angry, disgusted, fearful, happy, neutral, other, sad, surprised, unknown; embedding extraction exists (`extract_embedding`) | licence listed only as "model-license": **commercial terms UNVERIFIED**; embedding procedure not detailed on the card |
| Audio encoder C (research only) | `audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim` | outputs arousal/dominance/valence (~0-1) plus pooled last-layer states; 16 kHz; trained on MSP-Podcast v1.7 | **CC BY-NC-SA 4.0, "research purpose only"**: usable for hackathon experiments, **not** in a commercial product without audEERING's separate licence |
| Text encoder | `microsoft/deberta-v3-base` | MIT; 184M total params (86M backbone + 98M embeddings); 12 layers, hidden 768; NLU fine-tuning examples | max sequence length not stated on the page |
| Claim extraction / context | the existing LLM provider (Nebius gpt-oss-120b / local Ollama, via slice C) | n/a | outputs must be checked against transcript quotes |
| Speaker separation | ECAPA (already integrated) + Silero VAD | in repo and tested | stereo/two-channel recordings avoid diarization errors |

**Selection rule:** run encoders A and B (and C for research) frozen with the same small head on the pilot data; choose by held-out-speaker results, not by card claims. Do not assume any "emotion" checkpoint is valid for bluffing or intent; emotion recognition alone does not validate hidden-intention detection.

## 4. Data preprocessing (exact requirements)
- **Audio:** resample to 16 kHz mono for all verified encoders (WavLM and emotion2vec cards state 16 kHz; Whisper input handled by its feature extractor, rate **not stated** on the card page, use the pipeline's default and verify in code).
- **Speaker-separated, timestamped segments:** one segment per speaker turn from VAD (Silero), cap 30 s for Whisper's window; split longer turns with overlap and keep original call timestamps. Store `start_seconds`/`end_seconds` in call time.
- **Intensity is information:** do not normalize loudness away. Feed (a) the waveform normalized per segment for the encoder and (b) separate scalar features: RMS, peak, clipping fraction, estimated SNR, gain/device metadata. Test how mic distance, gain, compression and noise move the scores (augmentation sweeps) before trusting any weight.
- **Quality gates:** flag segments with clipping, SNR below a threshold, or under ~1 s; they get `insufficient_evidence`, not a score.
- **Timestamp alignment:** Whisper word timestamps give text-to-audio alignment; verify alignment drift on 10 manually checked segments before use.

## 5. Dataset schema and annotation
Use the brief's call-level schema (complete calls, speaker-separated segments, linked annotations), extended with explicit provenance:
```json
{"call_id":"call_014","scenario":"commercial_negotiation","consent_ids":["spk03","spk07"],
 "segments":[{"segment_id":"seg_008","speaker_id":"seller_014","role":"seller",
   "audio_file":"call_014_seller_008.wav","start_seconds":92.4,"end_seconds":100.8,
   "text":"That is the lowest price we can offer.","channel":"laptop","gain_db":null,
   "annotations":{"perceived_emotion":null,"arousal":null,"delivery_mode":"unknown","answer_responsiveness":"unknown"},
   "annotation_sources":{"perceived_emotion":"human_annotation"}}],
 "events":[{"target":"negotiating_bluff","evidence_segment_ids":["seg_008"],
   "ground_truth":"bluff|honest|unknown","ground_truth_source":"private_card"}],
 "speaker_card_ref":"card_seller_a","split":"train"}
```
Rules: `unknown` stays unknown and is **masked in the loss**; never 0. Keep apart: perceived emotion vs self-report; perceived deception vs verified; reading/rehearsal vs intentional falsehood; expressed interest vs verified intent; unsupported answers vs knowing fabrication. Define each scale and the annotator instruction sheet before labeling. Annotators are blind to cards and conditions; report weighted kappa; drop a label with kappa < 0.4.

## 6. Ground-truth strategy: controlled negotiations
Private information cards make the truth known without guessing:
- **Seller card:** product facts, true floor price, which constraints are flexible. Conditions: *honest* (states real limit), *bluff* (states a flexible limit as fixed), *improvise* (asked beyond the fact sheet; either says "I don't know" or invents), *rehearsed* (reads a prepared pitch) vs *spontaneous*.
- **Buyer card:** true budget and assigned intent: *genuine*, *polite-but-uninterested* (feigns interest), *undecided*. Verified by the card plus a post-call commitment step.
- **Surprise follow-ups** scripted for the counterpart ("what happens if we sign next week?", "can you show me the spec?") to create the rehearsed-to-unprepared contrast the brief describes.
- Balance and randomize roles, conditions, scripts and recording setups across speakers so none predicts the label. Small incentive (e.g. prize for the best negotiator) so stakes are not zero. Debrief everyone; stop word available.
- **Limit that must be stated on any slide:** staged, instructed behavior in a controlled task. It does not establish reliability on real calls; production needs separate validation.
- Recruit volunteers beyond the team. With 2-4 speakers we can build the pipeline and a pilot, not a validated detector.

## 7. Model design
**Audio branch.** Pretrained encoder, 16 kHz waveform in, frame states out. Start **frozen** with a learnable weighted sum of layer outputs and attention pooling per segment (frozen-first is deliberate given a tiny labeled set). If a pilot set exceeds roughly several hours of labeled speech from 20+ speakers (threshold is a judgement call, `UNVERIFIED`), unfreeze the top layers or use LoRA. Whether PEFT's LoRA covers these audio encoders is **UNVERIFIED** (the PEFT docs page fetched did not state modality support; test on the real model, fallback is unfreezing the top 2 layers). Keep the full-layer segment embedding, not just emotion probabilities, so delivery information survives to fusion.
**Text branch.** Whisper transcript per segment plus a window of preceding turns, encoded by DeBERTa-v3-base (start frozen, LoRA or top layers later), plus LLM-extracted event features: claims, commitments, answer-responsiveness, specificity, hedging, contradictions with earlier statements or the fact sheet.
**Speaker history.** Per speaker, rolling statistics of embeddings and acoustic features over earlier spontaneous speech; the model sees the *delta* from that speaker's own history, plus persistence and recovery over time.
**Fusion.** Per segment: [audio embedding, text embedding, scalar acoustic features, history deltas, event features (question type, follow-up surprise, response latency)] into a cross-attention or concat-MLP block. Use **modality dropout** in training so audio-only and text-only predictions come from the same model, and so a stronger text signal cannot hide a useless audio branch.
**Call-level temporal model.** A small GRU/Transformer over each speaker's segment sequence feeds the heads; event targets whose evidence segments are unknown use attention-based multiple-instance pooling (label at call/event level, model finds the evidence segments).
**Heads and losses.** One head per target. Masked loss per head: BCE for binary, CE for categorical, ordinal/MSE for scales; class weights for imbalance; unknown labels contribute zero loss. Simple weighted sum of head losses with weights tuned on validation; no cross-target averaging at inference.

## 8. Evaluation
- **Splits:** by speaker, call and scenario at once; no speaker, script, role or setup appears in two splits. Prefer leave-one-speaker-out when N is small.
- **Required comparison:** text-only, audio-only, fused. Audio ablation must not corrupt the transcript (zero or mask the audio branch rather than editing the text; verify text is byte-identical). Primary question: **does audio add predictive value for the actual target?** Report the delta with a bootstrap CI (resample calls, not segments).
- **Baselines:** always-prior; hand-crafted prosody z-scores plus logistic regression; fact-sheet contradiction check on text.
- **Metrics per target:** precision, recall, false-positive and false-negative rates (false accusation is a consequential error), AUC with CI, calibration curve and ECE, abstention rate and performance on non-abstained cases.
- **Shortcut audit:** can speaker identity, role, script, device or loudness alone predict the label? If so, that is what the model learned.
- **Robustness:** noise, gain, compression, mic distance, accents, speaking styles.

## 9. Live inference, calibration, deployment
- **Latency.** Existing repo measurements (3 demo clips, Mac, `results/history.csv`): Whisper large-v3-turbo via mlx, mean per-utterance total about 984 ms; speaker/spoof detectors tens to low hundreds of ms. Live target: score within ~1.5 s of the end of a turn, hints update per turn; post-call report runs batch on the full call. Fusion and heads are negligible next to the encoders. Expect the encoder passes for audio and text to be the cost; measure, do not assume.
- **Calibration.** Per target, on a held-out calibration set from speakers not in training: temperature or isotonic scaling, ECE with CI. Until then `calibration_status: "not_established"`, `calibrated_probability: null`, UI says "model score". Even once calibrated, the statement is scoped: "in controlled negotiations like our test set, scores near 0.7 were bluffs about X% of the time". Add an abstain band; `insufficient_evidence` is a normal output.
- **Output contract.** The brief's: `deception_assessment` (target, `model_score`, `calibrated_probability`, `calibration_status`, evidence segments, alternative explanations, status), `delivery_assessment`, `emotion_timeline`, `live_hints`, `post_call_summary`. No score without evidence segment IDs; no invented acoustic measurements; hints state acoustic observation, content, comparison interval, hypothesis and alternatives, e.g. "possible prepared response ... may reflect rehearsal, uncertainty or another explanation. Ask for a concrete example."
- **Post-call report:** the seven items in the brief (trajectories, significant acoustic changes with timestamps, claims/inconsistencies, hypotheses, scores with calibration status, alternatives, discriminating follow-up questions), observations separated from inferred motives and verified facts.
- **Consent, retention, access.** All-party consent before any recording or analysis, with a plain statement of what is scored. Raw audio and embeddings stay local, encrypted at rest; access limited to named team members; delete on request; retention proposal 30 days for raw audio unless the participant opts in longer (**decision for the team**). Embeddings of voices count as biometric-adjacent data. Humans decide; scores never trigger automated action. Not for hiring, lending or any decision about a person's rights.

## 10. Sources opened this session (2026-10-10)
- https://huggingface.co/emotion2vec/emotion2vec_plus_large
- https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim
- https://huggingface.co/microsoft/wavlm-base-plus
- https://huggingface.co/openai/whisper-large-v3-turbo
- https://huggingface.co/microsoft/deberta-v3-base
- https://huggingface.co/docs/peft/main/en/index (did not state audio-model support)
Pages were summarized by the fetch tool, not read in full: quotes above come from those summaries. Run the claim audit (`hallucination-detector`) on this file before it goes into slides or external material.

## 11. Hackathon-feasible path (honest scope)
1. Ship the pipeline with **frozen** encoders and small heads; no full fine-tune tonight.
2. Run the controlled-negotiation pilot with whatever consenting volunteers we get (tens of calls at most).
3. Report audio-only vs text-only vs fused with CIs; if audio adds nothing for a target, say so and show only the labeled signal that holds up.
4. Demo shows live hints and a post-call report with `calibration_status: not_established`, evidence timestamps and alternatives.

## 12. Open decisions for the team
- How the application layer (C) consumes these scores for the elderly scam-prevention story (e.g. scam-call scenes recorded as extra scenarios, hints worded for a protective, human tone). Decided: the application is not changed by this plan.
- Who the volunteers are; whether we can run a compute job on the 5090 or stay on the Mac (MPS/mlx).
- Raw-audio retention period and consent wording.
- Licence sign-off before shipping any checkpoint commercially (emotion2vec terms, WavLM LICENSE, audEERING is non-commercial).
