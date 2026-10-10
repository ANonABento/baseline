# Skeptical review: voice_state and spoof claims (2026-10-10), CP3
Independent reviewer, read-only, from raw outputs. Saved verbatim in substance by V (condensed). EXPLORATORY; no locked protocol. **Verdict: PARTIALLY SUPPORTED.** Docs disclaim lie detection consistently; naming and held-out wording were overstated.

## Blockers (all addressed in the commit after this review)
1. "stress_related_change" is not defensible as a name: the score uses abs(z) (`voice_state.py`), so quieter, flatter or slower speech raises it; RAVDESS shows calm 0.63 and sad 0.79 flagged. Fix: neutral alias `delivery_change`, user-facing text "change vs this speaker's earlier delivery"; plan wording rule revised.
2. `finetuning_plan.md` listed "an attempt to conceal something" as a cause: deception inference. Removed.
3. `architecture.md` mislabelled results: 79.9% RAVDESS is a single-clip rule without the persistence step; 9.5% is an unweighted mean of 14 session rates (median 0, one session 93%). Reworded.
4. The 12/16 and 15/40 spoof breakdowns had no saved per-clip file. Saved `results/spoof_per_clip_2026-10-10.csv` (parsed from eval stdout) with Wilson CIs.

## Major (status)
- Pseudo-replication: CIs resample sessions, not people (30 sessions / 19 ids). Wording fixed; per-person bootstrap NOT done.
- Tune/report halves are person-disjoint but share meetings (room, channel, topic). Disclosed; split by meeting NOT done.
- Forking paths: three tuning runs, deviations only in a script docstring, defaults changed after seeing results on the same data. Report half is not a clean holdout. Disclosed.
- Grid is 48 settings (24 distinct on RAVDESS), not 96; chosen AMI rate 0.08 is near the 0.15 cut, selection fragile.
- Spoof uncertainty: Wilson CIs added; real class is audiobook audio, not phone/mic speech.
- Workplan status: 1.2 and 2.1 re-marked partial.
- Provenance: results from dirty trees; AMI revision not pinned.
- Confounds: acted arousal is not stress; uncalibrated dBFS; RAVDESS baseline and test clips share sentences and session.

## What the data supports
Acted high vs low arousal separable from held-out actors (probe accuracy 0.771-0.828 vs 0.533 baseline). The sustained rule rarely fires in most AMI sessions but heavily in a few. The spoof detector catches say/pitch fakes and ~75% of ElevenLabs flash clips with ~37.5% false positives on audiobook speech. Nothing supports stress detection, validated calibration or lie detection.

## Tests that would separate alternative explanations (not run)
Split by meeting and inject gain/codec changes; sign-specific rule (rising F0 and loudness only) vs calm/sad flags; stratify AMI flags by utterance length; real phone/mic speech through the same spoof path; energy-only baseline on the same folds. A speech scientist and a statistician should confirm the per-person reanalysis and the renaming before any slide.
