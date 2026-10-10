# Public-data checks (EXPLORATORY), 2026-10-10

Source: `results/public_checks.json` (`scripts/public_checks.py`, seed 0) and `results/tune_voice_state.json` (`scripts/tune_voice_state.py`). Data: AMI ihm subset (30 speakers), LibriSpeech test-clean (40 speakers), RAVDESS (24 actors, 1,440 acted clips). CIs are 95% percentile bootstrap resampling speakers or actors. Nothing here has stress ground truth; **acted emotion is not real stress** and none of it is lie detection.

## Thresholds (tuned, then reported on a held-out half)
Setting chosen by the rule in `tune_voice_state.py` (two documented deviations): a feature counts at abs(z) >= 2.5, at least 2 features together, sustained over 3 utterances, baseline of 3 usable utterances. Tune half: 10 AMI speaker ids (16 speaker-meeting sessions), RAVDESS actors 1-12. **Report half** (different people): AMI sustained-change rate **9.5%** (CI 0.7 to 22.9%, 14 speaker-meeting sessions from 9 ids); RAVDESS high-arousal clips flagged **79.9%** and held-out calm/neutral clips flagged **16.7%** (12 actors, single-clip rule). The first defaults (abs(z) >= 2, 2 utterances) fired far too often on ordinary AMI speech: about 55% per-speaker sustained-change rate in an earlier run whose output was overwritten (**UNVERIFIED from files**; the tune-half grid row z=2, baseline 3, 1 feature, sustain 2 records 57%). Still optimistic for unseen speakers and channels; the AMI false-alarm upper bound is not under 15%.

## A. AMI ordinary speech, final defaults (30 speakers, all used in tuning)
Sustained-change rate 8.7% (CI 2.4 to 17.3%); any single feature beyond threshold in one utterance 60.4% (CI 51.1 to 69.1%), so single-utterance excursions are common in normal speech. 67.8% of utterances pass the quality gate.

## B. Read (LibriSpeech) vs spontaneous (AMI), speaker means. CONFOUNDED (corpus, channel, speakers)
| Feature | LibriSpeech | AMI | Cohen's d (AMI minus LS) |
|---|---|---|---|
| pause fraction | 0.300 | 0.323 | 0.44 |
| energy-peak rate /s | 4.94 | 4.94 | -0.02 |
| pitch spread (st) | 5.06 | 4.39 | -0.63 |
Pause fraction and pitch spread differ modestly in the expected direction; rate proxy does not. Not evidence about reading itself.

## C. RAVDESS (acted), actor-held-out folds
Emotion probe, accuracy (CI over actors): 8-class, majority baseline 0.133: prosody-5 0.353 (0.327-0.378), prosody-5 actor-normalised 0.422 (0.394-0.450), prosody-5 + MFCC 0.430 (0.392-0.466). High vs low arousal, majority baseline 0.533: 0.771, 0.828 (0.801-0.856), 0.756. The hand-built features separate acted arousal clearly and acted categories weakly. Change vs the actor's own neutral clips (share of clips with any feature beyond threshold): angry 0.96, fearful 0.95, surprised 0.95, happy 0.91, disgust 0.90, sad 0.79, calm 0.63, neutral 0.29 (held-out neutral).
Limitation: RAVDESS clips skip the quality gate (short scripted utterances); acted performance exaggerates cues.
