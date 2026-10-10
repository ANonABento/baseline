# Fine-Tuning Plan: Voice + Content Signal Summaries (no lie detection)

> **Frame update (2026-10-10, Dae + Kevin):** the demo is a **customer vs scammer simulation**: the **human plays the scammer** and our AI pushes back and applies pressure (e.g. as the bank agent asking verification questions); interviews are one use case, not the demo (corrected 2026-10-10). We extract real-time **behavioural signals** (tone drift, speech rate, hesitation, de-escalation/recovery latency, response latency, talk-over, hedging, verification attempts, refusals) plus the person's **operational decisions**, show them on a **live Digital Twin dashboard**, and end with an **independently verifiable credential** (Ed25519 `did:key`, verifiable offline in `docs/verify.html`). Still **no lie detection, no skill or suitability claim**: the credential attests what was observed in one simulated call. Details: [`architecture.md`](architecture.md), UI contract: [`ui_spec_signals.md`](ui_spec_signals.md).
>
> **What is learned vs rules (honest):** *learned*: pretrained spoof detector (third-party), ECAPA speaker embeddings (third-party), frozen WavLM + logistic emotion probe trained by us on RAVDESS acted speech (`scripts/train_emotion_probe.py`; held-out actors 0.751 on 8 classes, acted only). *Rules, thresholds tuned on public data*: voice-state delivery change, session signals, decision tagging (keywords). Nothing is fine-tuned end to end; the demo exercises every piece listed here.

> **Decision update (2026-10-10, Dae): signals first, deception readings secondary.**
> - **Product:** a trust profile for voice interactions with stakes, like a credit score ("credit score for interviews", generalised to a credit-score-like trust profile for speakers, callers and clients in any voice interaction with stakes). We show the signals and what they *could* mean, hedged and with alternatives; deception is one possible reading, never a verdict. Not pure lie detection.
> - **Demo:** scam-call simulation: a **human plays the scammer**, our AI pushes back and applies pressure (e.g. as the bank agent asking verification questions). The live Digital Twin dashboard shows the scammer's real-time behavioural signals and operational decisions, backed by the independently verifiable Ed25519 `did:key` credential ([`verify.html`](verify.html)). Interviews are one use case, not the demo.
> - **Primary outputs = signal scores:** tone drift, speech rate, hesitation, de-escalation/response latency, emotion, arousal, delivery, each also as a delta vs the speaker's own baseline.
> - **Model (`notebooks/baseline_brief_architecture.ipynb`):** Stage A signal model (WavLM-base-plus top 4 + DeBERTa-v3-base top 2 layers fine-tuned, acoustic scalars, modality dropout) trains only on emotion, arousal, delivery. Measured per-turn signals `pitch_st_median`, `pitch_st_spread` (robust IQR, semitones re 100 Hz, `librosa.yin`), `voiced_frac`, `loudness_db`, `pause_frac`, `speech_rate_wps`, `filler_rate` (um/uh/I mean/like/...), `log_words`, `has_audio`, each with a delta vs the speaker's own earlier turns; response latency is a conversation event; all exposed as `signal_timeline`. Stage B (causal GRU per speaker over signals + deltas + speech embedding) also gives bluff / fabrication / mismatch **model scores: secondary and optional**. Data: this run's synthetic data has only 6 bluff and 12 mismatch labels (30 negotiation turns), so those heads report `insufficient_evidence`; fabrication has 180 synthetic audio labels plus Diplomacy text; more negotiation calls are needed if bluff/mismatch scores are ever wanted. An LLM reading `signal_timeline` is an alternative reader (not built).
> - **Safeguards:** consent-only; uncalibrated model scores (`calibration_status: not_established`); a human decides; never "is lying". Deception labels are text-only (Diplomacy) or TTS-synthetic, so audio's value for deception on real speech is untested. The live backend has no deception key; the notebook model is not integrated.

Status: **PLAN**; the notebook's full run is in progress on the RTX 5090 (results pending, [`train_on_gpu_machine.md`](train_on_gpu_machine.md)). Owner: V. Updated 2026-10-10 after team decision. Model side only; the application and pitch (slice C) stay human-connection oriented, e.g. scam prevention for elderly callers.

*(History: the no-deception-output rule below is replaced by the decision update above.)* **Decision (supersedes the earlier "target-specific deception scores" draft and the source brief's deception-score requirement):** the system does **not** detect lies and outputs **no** deception, bluff or fabrication score or label. It summarizes *observable voice and content signals* (high stress-related change, choppy delivery, monotone/read-like delivery, evasive or unresponsive answers) and states, with hedges, what such patterns *can* mean, including benign causes. The human decides.

Labels: **VERIFIED** = read on the model card/page this session (URLs in §10). **UNVERIFIED** = from memory or not stated. Everything the model outputs is a `PREDICTION` until tested on held-out data.

## 1. Scope and non-negotiables
- **Model side only.** The brief's commercial scenarios (negotiation, sales) are *examples* used to design controlled data. How an application uses the summaries is owned by C.
- Fine-tune pretrained models; no foundation model from scratch (a new task head is fine).
- Voice is central: keep the waveform and learn from acoustic embeddings; text is complementary evidence.
- Analyze **trajectories** across the call (change vs the same speaker's own earlier delivery), not isolated lines.
- Keep **observations**, **model interpretations** and **verified facts** separate in every output.
- No inference of intent or honesty from tone. Contradictions with earlier statements or a fact sheet are reported as *inconsistencies*, not lies.
- Consent-based conversations only. Not for lending decisions or biometric emotion screening.

## 2. What the model outputs
| # | Output | What it is | Source of truth for training/validation |
|---|---|---|---|
| S1 | `emotion_estimate` | perceived emotion mix and arousal/valence/dominance per segment (stressed, angry, worried, calm, engaged) | human annotation of perceived emotion; self-report kept separate |
| S2 | `stress_related_change` (contract key; shown to users as "change vs this speaker's earlier delivery"; the score is sign-agnostic: quieter, flatter or slower speech also raises it) | size of change in pitch, energy, rate, pauses vs the speaker's own baseline, with persistence and recovery | computed features plus annotation; speaker check-in |
| S3 | `delivery_markers` | choppiness (fragmented speech, irregular pauses), monotony, read-like/rehearsed delivery, response latency | computed features plus annotation (`delivery_mode`) |
| S4 | `content_observations` | answer responsiveness, specificity, hedging, contradiction with earlier statements or a provided fact sheet | annotation plus fact-sheet check |
| S5 | `interpretation_notes` | hedged mapping "pattern X can indicate Y, or Z, or W" with a suggested neutral follow-up question | rule/LLM-written from S1-S4, constrained to measured signals |
| S6 (optional, secondary) | `deception_assessment` (bluff, fabrication, mismatch) | Stage B model scores read from the signals + speech; one possible interpretation, never a verdict | Diplomacy (text) + ElevenLabs scripted calls (TTS); this run's synthetic data has only 6 bluff and 12 mismatch labels (30 negotiation turns), so those heads report `insufficient_evidence`; fabrication has 180 synthetic audio labels plus Diplomacy text; more negotiation calls are needed if bluff/mismatch scores are ever wanted |

Each output is a model score or label with a confidence level and can be `insufficient_evidence`. **There is no deception, bluff or fabrication output.** *(Now: optional secondary S6.)* Percentages, if shown, are model scores about the *signal* ("stress-related change: 0.62 vs her baseline"), not probabilities about truthfulness; calibration status is shown (`not_established` until validated).

**Interpretation table (hypotheses; evidence status from [`research/voice_signal_evidence.md`](research/voice_signal_evidence.md), read via a summarising fetch tool, 3 key PDFs unreadable, so treat as a first pass and re-check before external use).** Illustrative wording the agent may use:
| Observed pattern (with timestamps) | Can be consistent with | Neutral follow-up | Evidence status |
|---|---|---|---|
| sustained stress-related rise after a specific question | pressure, discomfort with the topic, uncertainty, rehearsal breaking down, a stressor unrelated to the call or a change of topic or channel | ask a concrete, open question about that topic | PARTLY: a systematic review reports higher mean F0 under stress in 15 of 19 studies; effects vary by person; deception cues are weak (DePaulo 2003 abstract). The own-baseline premise is a HYPOTHESIS | |
| choppy/fragmented delivery with long pauses | searching for an answer, nervousness, poor connection, language fluency, or hesitation about what to disclose | give time; ask for an example | PARTLY/UNVERIFIED: pause evidence rests on one study as quoted in a review; "poor connection" and "fluency" are common-sense confounds, no source | |
| monotone, evenly paced delivery | reading from notes, rehearsal, fatigue, or a calm temperament | ask an unexpected but fair follow-up | UNVERIFIED: no opened source covers read-vs-spontaneous prosody; HYPOTHESIS | |
| answer that does not address the question | misunderstanding, evasion, distraction | restate the question | UNVERIFIED: weak support for evasion only; HYPOTHESIS | |
Wording rule (revised after the skeptical review): show "change vs this speaker's earlier delivery"; "stress-related" is a hypothesis about one possible cause, not a label the data supports; never "the speaker is stressed" and never "is lying".

## 3. Pretrained checkpoints
| Role | Candidate | Verified facts | Open questions |
|---|---|---|---|
| ASR + timestamps | `openai/whisper-large-v3-turbo` (already in the repo via mlx-whisper) | MIT licence; 30 s receptive field, chunked for longer audio; sentence and word timestamps (`return_timestamps`); 809M params; pruned decoder (32 to 4 layers), "minor quality degradation" | none for the hackathon |
| Audio encoder A | `microsoft/wavlm-base-plus` | 16 kHz input; pretrained on 94k h (Libri-Light, GigaSpeech, VoxPopuli); English; no tokenizer; needs fine-tuning for downstream tasks | licence is linked to a LICENSE file; a fetch summary returned odd "CC BY-SA 3.0" boilerplate, so **terms UNVERIFIED: a human must read the file** |
| Audio encoder B (emotion-pretrained) | `emotion2vec/emotion2vec_plus_large` | 16 kHz; ~300M params; labels: angry, disgusted, fearful, happy, neutral, other, sad, surprised, unknown; embedding extraction exists (`extract_embedding`) | HF card `license: other` ("model-license", FunASR); a summary of that licence shows free use/modify/share with attribution and no explicit commercial ban, while the GitHub page shows an MIT badge: **sources disagree, human sign-off needed**; embedding procedure not detailed on the card |
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
Complete calls, speaker-separated and timestamped, original audio kept beside text (transcripts alone are insufficient):
```json
{"call_id":"call_014","scenario":"controlled_conversation","consent_ids":["spk03","spk07"],
 "segments":[{"segment_id":"seg_008","speaker_id":"spk03","role":"role_a",
   "audio_file":"call_014_spk03_008.wav","start_seconds":92.4,"end_seconds":100.8,
   "text":"That is the lowest price we can offer.","channel":"laptop","gain_db":null,
   "annotations":{"perceived_emotion":null,"arousal":null,"delivery_mode":"unknown","answer_responsiveness":"unknown"},
   "annotation_sources":{"perceived_emotion":"human_annotation","self_reported_stress":"speaker_check_in"}}],
 "condition":{"name":"instructed_pressure_level_2","source":"scripted_condition"},
 "split":"train"}
```
Rules: `unknown` is masked in the loss, never 0. Keep apart: perceived emotion vs self-report; reading/rehearsal vs anything about honesty. The `condition` field records the *experimental manipulation* (what the speaker was asked to do), not an inner state and not a deception label. Define scales and annotator instructions before labeling; annotators are blind to condition; report weighted kappa; drop a label with kappa < 0.4.

## 6. Data: open datasets only (decision 2026-10-10, Dae: no self-recorded training data)
Details, licences and access checks: [`research/open_datasets.md`](research/open_datasets.md) (licence text read via a summarising fetch tool; human sign-off needed in `docs/licences.md` before any commercial use).
| Role | Dataset | Why | Caveat |
|---|---|---|---|
| Read speech (S3 read class, spoof real class) | LibriSpeech (CC BY 4.0) | already in the repo; many utterances per speaker | read audiobook audio |
| Spontaneous conversation (S2, S3, S4) | AMI (HF `edinburghcstr/ami`, CC BY 4.0, ~100 h, 47 speaker IDs, transcripts, dialog acts, ~29 GB so use a subset) | multi-turn meetings give per-speaker history and content | corpus, channel and speaker population differ from LibriSpeech, so read-vs-spontaneous is confounded |
| Emotion / arousal prototype (S1) | CREMA-D (ODbL, share-alike; official access path ambiguous) and RAVDESS (CC BY-NC-SA, research only) | categorical emotion plus intensity, many actors | **acted**, categorical not dimensional; non-commercial limits |
Not available tonight (signed agreement or fee): MSP-Podcast (best arousal fit), IEMOCAP, ESD, BESST, SUSAS, Switchboard, VoxCeleb. No open dataset opened has stress ground truth relative to a speaker's own baseline, so **S2 (stress-related change vs baseline) stays an unvalidated HYPOTHESIS**: we can build it from prosody z-scores and show it on public audio, but cannot claim it measures stress.
- **What this changes vs the earlier plan:** no scripted-pressure manipulation check and no team-voice baselines. Replaced by (a) held-out-speaker agreement of S1 with CREMA-D/RAVDESS labels, (b) whether S3 read-like markers separate LibriSpeech (read) from AMI (spontaneous) with the corpus confound stated, (c) a sanity check that z-score changes track within-AMI-speaker variation, labelled exploratory.
- Self-recorded scenes (`recording_protocol.md`) are **not used**. The elderly-scam scenes remain scenarios for C's demo, built from text-to-speech and public audio.
- **Limit for any slide:** acted emotion is not real stress; read vs spontaneous is confounded by corpus; with no real-stress ground truth, S2 is shown as "change vs this speaker's earlier delivery", never as measured stress.

## 7. Model design
**Audio branch.** Pretrained encoder, 16 kHz waveform in, frame states out. Start **frozen**: learnable weighted sum of layer outputs and attention pooling per segment (frozen-first is deliberate with a tiny labeled set). Unfreeze top layers or use LoRA only if the labeled set grows enough (threshold is a judgement call). PEFT/LoRA support for these audio encoders is **UNVERIFIED** (the PEFT page fetched did not say); test on the real model, fallback is unfreezing the top 2 layers. Keep full segment embeddings, not only emotion probabilities.
**Text branch.** Whisper transcript per segment plus preceding turns, DeBERTa-v3-base (frozen first), plus LLM-extracted observations (claims, commitments, responsiveness, specificity, hedging, contradictions with earlier statements or the fact sheet), each quoted from the transcript.
**Speaker history.** Rolling statistics of each speaker's earlier embeddings and acoustic features; the model sees the delta from that speaker's own history, plus persistence and recovery.
**Fusion.** Per segment [audio embedding, text embedding, scalar acoustic features incl. loudness/quality, history deltas, question type, response latency] into a concat-MLP or cross-attention block with **modality dropout**, so audio-only and text-only predictions come from the same model and a strong text signal cannot hide a useless audio branch. A small GRU/Transformer over each speaker's segments handles trajectories.
**Two-stage split (2026-10-10).** Stage A heads: emotion, arousal, delivery. Measured per-turn signals and their deltas vs the speaker's own earlier turns form the primary `signal_timeline` and feed Stage B, which adds the optional S6 scores.
**Heads and losses.** Heads for S1-S3 (and `delivery_mode` / `responsiveness` classification). Masked loss: CE for categorical, ordinal/MSE for scales, class weights for imbalance; unknown labels contribute zero loss. S4-S5 come from the LLM layer constrained by measured signals; no learned honesty head exists.

## 8. Evaluation
- **Splits** by speaker, call and scenario at once; no speaker, script, role or setup in two splits; leave-one-speaker-out when N is small.
- **Required comparison:** text-only vs audio-only vs fused for each of S1-S3. Audio ablations must not corrupt the transcript (mask the audio branch; verify the text is byte-identical). Question: **does audio add value for the signal we claim?** Report the delta with a bootstrap CI (resample calls, not segments).
- **Public-data checks (replace manipulation checks):** S1 vs CREMA-D/RAVDESS labels on held-out actors; S3 read-vs-spontaneous (LibriSpeech vs AMI, confounded, say so); S2 within-speaker variation on AMI. Effect sizes with CIs; exploratory.
- **Baselines:** hand-crafted prosody z-scores + simple regression; energy-only; always-prior. If a fine-tuned model does not beat prosody z-scores, ship the z-scores and say so.
- **Metrics:** per-output accuracy/F1 or correlation with annotators (for S1-S3), calibration curve and ECE where percentages are shown, abstention rate and performance on non-abstained cases; **false-alarm rate on calm and honest-but-anxious speakers** (an anxious person must not look suspect).
- **Shortcut audit:** can speaker identity, role, script, device or loudness alone predict the label? Robustness to noise, gain, compression, mic distance, accents, speaking styles.

## 9. Live inference, output contract, deployment
- **Latency.** Existing repo measurements (3 demo clips, Mac, `results/history.csv`): Whisper large-v3-turbo via mlx, mean per-utterance total about 984 ms (history.csv row 2026-10-09T21:44:45); per-detector latency is not recorded in `results/history.csv` (only whole-run `mean_utt_ms`, e.g. 75.6 and 340.7 on other rows), so it is UNMEASURED per detector. Target: update within ~1.5 s after each turn; post-call report runs batch. Measure, do not assume.
- **Output contract (proposal, not agreed with C):**
```json
{"call_id":"...", "segment_id":"seg_008", "speaker_id":"...",
 "observations":{"emotion_estimate":{"stressed":0.41,"calm":0.30,"angry":0.05},"stress_related_change":{"score":0.62,"vs":"own_baseline_0_20s","calibration_status":"not_established"},
   "delivery_markers":{"choppiness":0.55,"monotony":0.2,"read_like":0.1},"content":{"responsive":false,"inconsistent_with":["seg_003"]}},
 "interpretation_notes":["Sustained rise in stress-related vocal signals after the verification question; can reflect pressure, uncertainty, or other causes."],
 "suggested_follow_up":"Ask an open question about that topic.",
 "evidence":{"segments":["seg_007","seg_008"],"comparison_interval":[0,20]},
 "status":"ok|insufficient_evidence","limitations":["Vocal signals do not establish internal state","No inference of honesty or intent"]}
```
  No score without evidence segment IDs; no invented acoustic measurements; observations, interpretations and verified facts in separate fields.
- **Post-call report:** emotion and delivery trajectory per speaker, significant acoustic changes with timestamps, content observations and inconsistencies, interpretation notes with alternatives, unresolved evidence, discriminating follow-up questions.
- **`signal_timeline` (2026-10-10, notebook `assess_call`, primary output):** per turn `{segment_id, speaker, t_start, signals{...}, delta_vs_own_earlier_turns{...}}`; feeds the Digital Twin dashboard and any LLM reader. Optional S6 scores sit in `deception_assessment` (`calibration_status: not_established`, evidence segment IDs, alternative explanations).
- **Consent, retention, access.** All-party consent before recording or analysis, stating exactly what is scored. Raw audio and embeddings local, encrypted at rest, named access only, deletion on request; retention proposal 30 days for raw audio (**team decision**). Voice embeddings are biometric-adjacent. Humans decide; outputs never trigger automated action.

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
2. Pilot: controlled conversations with whatever consenting volunteers we get.
3. Report audio-only vs text-only vs fused and the manipulation checks with CIs; if audio adds nothing, say so and show only the signal that holds up.
4. Demo-side (C): live hints and post-call summary with observations, hedged interpretation notes and `calibration_status: not_established`.

## 12. Open decisions for the team
- How the application layer (C) consumes these summaries for the elderly scam-prevention story; hint wording stays C's.
- Volunteers beyond the team; 5090 availability vs the Mac (MPS/mlx).
- Raw-audio retention period and consent wording.
- Primary-source check of every row in the interpretation table (§2) before it is shown as fact.
- Licence sign-off before shipping any checkpoint commercially (emotion2vec terms, WavLM LICENSE; audEERING is non-commercial).
