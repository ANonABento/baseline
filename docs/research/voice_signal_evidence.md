# Voice/delivery signal evidence (Baseline interpretation table)

Date: 2026-10-10. Type: literature check, EXPLORATORY. Scope: research planning only.
Method caveat: pages were read through a fetch tool that returns summaries. Quotes below are what that tool returned. Two PDFs (DePaulo full text, NIJ 221502 report) and the Harnsberger 2009 PDF could not be rendered (no PDF renderer, binary text), so they were NOT read; claims depending on them are UNVERIFIED. PubMed returned a cookie wall. No retraction/correction check was run (UNVERIFIED for all papers).

## 1. Interpretation table (finetuning_plan.md section 2)

Verdict scale: SUPPORTED / PARTLY / UNSUPPORTED / UNVERIFIED. All concern "can be consistent with", never "indicates".

| Row | Claim | Verdict | Source opened and passage |
|---|---|---|---|
| 1 | Stress-related vocal rise (pitch/energy) can be consistent with pressure/discomfort | PARTLY | Systematic review, PMC12289014 (https://pmc.ncbi.nlm.nih.gov/articles/PMC12289014/): "fifteen out of nineteen studies reported a significant increase in mean F0" under stress; four inconsistent; speech rate "heterogeneous"; 38 articles / 39 studies, 35.9% high, 30.8% low methodological quality. Limitation quoted: individual coping styles change how stress shows in speech. |
| 1 | ...or "an attempt to conceal something" | PARTLY | DePaulo 2003 abstract (https://scholars.duke.edu/publication/660134): liars "are more tense"; but "many behaviors showed no discernible links, or only weak links, to deceit"; cues stronger when motivated and for transgression lies. Effect size for vocal tension/pitch: UNVERIFIED (full text not read). Keep "concealment" only as one listed alternative among benign causes. |
| 1 | Sustained rise vs the speaker's own baseline is a better signal than absolute values | UNVERIFIED | Review notes inter-individual variation (above); no opened source tests within-speaker baselining. HYPOTHESIS. |
| 2 | Long pauses / fragmented delivery can be consistent with searching for an answer / cognitive load | PARTLY | Search snippet of Christodoulides (UCLouvain, "Effects of Cognitive Load on Speech Production") reported more and longer silent pauses under load; the page was NOT opened -> UNVERIFIED as a citation. PMC12289014 (opened): cognitive load, F0 up in 6/10 studies, intensity up in 3/3, speech rate "mixed". So pause claim = UNVERIFIED, rate claim = mixed. |
| 2 | ...or nervousness | PARTLY | Same stress review: one study (Bucharan 2014, as quoted by the review) reported more and longer pauses under stress; single study. |
| 2 | ...or poor connection / language fluency | UNVERIFIED | No source opened. Common-sense confound, HYPOTHESIS. |
| 3 | Monotone, evenly paced delivery can be consistent with reading/rehearsal/fatigue/calm | UNVERIFIED | No opened source on read-vs-spontaneous prosody, fatigue or temperament. HYPOTHESIS. Pitch-variance decrease under high load appeared only in an unopened search snippet. |
| 4 | Non-responsive answer can be consistent with misunderstanding/evasion/distraction | UNVERIFIED | No source opened. DePaulo abstract supports only that liars are "less forthcoming" (PARTLY for evasion as a deception cue; weak). |

## 2. Specific questions

(a) Accuracy of voice-stress / voice-based deception detection
- DePaulo et al. 2003, Psychol Bull 129(1):74-118: 1,338 estimates of 158 cues; many cues no/weak link (abstract, Duke scholars page). Verdict: SUPPORTS "weak, context-dependent cues"; specific vocal d values UNVERIFIED.
- Damphousse jail study as reported by Science News (https://www.sciencenews.org/article/truth-hurts, secondary source): 319 arrestees checked against urine tests; "fewer than one-sixth of the lies were detected. LVA spotted about 10 percent of lies, while CVSA got nearly 20 percent"; truthful statements correctly identified 85-95% (as stated by the article). Primary NIJ report NOT read -> numbers are secondary, PARTLY verified.
- Search-snippet claims ("42-56% hit rates", "false positive 40-65%", "little or no scientific basis") come from unopened abstracts: UNVERIFIED, do not quote.
- Verdict: no opened evidence supports voice stress analysers as lie detectors. Consistent with the product not claiming lie detection.

(b) False positives on truthful but anxious speakers
- No opened source measures this directly. Indirect: stress-review limitation on individual differences; DePaulo shows tension is a weak cue. UNVERIFIED as a measured rate. HYPOTHESIS: anxious truthful speakers will show the same stress-related changes. Plan section 8 already requires testing this.

(c) Acted to spontaneous SER generalisation
- Milner et al. 2022, https://arxiv.org/abs/2207.02104 and ar5iv: abstract says acted emotions "may be over the top compared to less expressive emotions displayed in everyday life"; conclusion calls it "the first study of its kind investigating the degradation of performance when moving from acted to more natural datasets." Datasets: eNTERFACE, RAVDESS (acted), IEMOCAP (elicited), MOSEI (natural). Multi-domain training gave +2.2% weighted accuracy on MOSEI (as returned by tool). Search snippet said "transfer of information is not successful" for plain cross-corpus (abstract not fully opened). Verdict: PARTLY supported (degradation expected; size not verified here). Note MSP-Podcast annotator agreement: Cohen's kappa 0.411 for primary emotions (https://arxiv.org/html/2509.09791v1), i.e. labels on natural speech are noisy.

(d) Pause/rate/pitch vs own baseline and stress or cognitive load
- Group-level associations: PARTLY (F0 up with stress 15/19; with load 6/10; rate and pauses mixed/thin). Within-speaker baseline deltas: UNVERIFIED (not examined by opened sources).

(e) Licences
- emotion2vec_plus_large: HF YAML shown as `license: other`, `license_name: model-license`, `license_link: https://github.com/alibaba-damo-academy/FunASR`. FunASR MODEL_LICENSE (raw.githubusercontent.com/modelscope/FunASR/main/MODEL_LICENSE) tool summary: "free to use, copy, modify, and share"; must "attribute the source and author information and retain relevant model names"; no explicit commercial prohibition; no-liability clause. The GitHub emotion2vec repo shows an MIT badge, but no licence text was shown. Verdict: PARTLY resolved (permissive, attribution required); legal sign-off still needed because the text was summarised and the sources differ (MIT vs model-license). Also training data is ~40,000 h of pseudo-labelled data per the card summary; data provenance not verified.
- wavlm-base-plus: card links https://github.com/microsoft/UniSpeech/blob/main/LICENSE; fetched summary says "Attribution-ShareAlike 3.0 Unported" (Creative Commons text). This is odd for a model licence and the summary quoted only the CC boilerplate opening, so treat as UNVERIFIED and read the file directly. Card notes English-only, 16 kHz, needs fine-tuning.
- MSP-Podcast: paper (arXiv 2509.09791v1) says podcasts are 90.86% CC-BY and 5.59% CC-BY-SA, access requires signed data transfer agreements, 329 academic groups, 409 h, 3,641 speakers. Commercial licence price (US$10,000 first year, US$5,000 renewal) is from an unopened search snippet: UNVERIFIED. The UTD corpus page failed (certificate error). Action: check licence with UT Dallas before commercial use. Models trained on it (audEERING) are CC BY-NC-SA per the plan.

## 3. Safe wording

May say:
- "Increased stress-related vocal signals compared with this speaker's earlier delivery between 01:32 and 01:50."
- "Longer pauses and more fragmented delivery here; this can reflect searching for an answer, nervousness, a poor connection or language fluency, among other causes."
- "Evenly paced delivery; this can happen when reading, when rehearsed, when tired, or in calm speakers."
- "The answer did not address the question asked; consider restating it."
- "These are model estimates; calibration not established; they do not show a person's internal state."

Must not say:
- "The speaker is lying / deceptive / hiding something / bluffing."
- "The speaker is stressed / anxious / nervous" as fact.
- "Stress in the voice indicates dishonesty" or any deception probability.
- "Validated" / "accurate" / "X% reliable" for any signal before held-out, speaker-independent testing.
- "Monotone means reading from a script."

## 4. Gaps and conflicts
- Not read: DePaulo full text (vocal d values), NIJ 221502, Harnsberger 2009, cognitive-load pause papers, any read-vs-spontaneous prosody study, any within-speaker-baseline study.
- Heterogeneity: speech-rate results conflict across studies in the stress review.
- Licence texts for WavLM and emotion2vec need direct human reading; the tool's summaries disagree with the plan's expectations in places.
- All literature-derived inferences above are HYPOTHESIS until tested on the project's own pilot data.
