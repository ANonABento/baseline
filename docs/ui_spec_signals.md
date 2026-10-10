# UI spec for the signals, Digital Twin and credential (V to C)

Everything below already exists in the backend payloads. Wording rule everywhere: **"change vs this person's earlier delivery"**, never stress, lying, honesty or skill.

## 1. Live (per utterance, from `signal` events with `signal == "prosody"`, `details`)
| Key | Show as |
|---|---|
| `status` | `building_baseline` -> "learning this person's normal (n of 3)"; `insufficient_evidence` -> grey "not enough clear audio"; `ok` -> live values |
| `delivery_change` (0..1 or null) | gauge "Change vs earlier delivery"; null = no gauge |
| `delivery_markers` (strings) | chips under the gauge, max 3 |
| `z` (pitch, spread, loudness, rate, pauses) | five small bars "vs own baseline" (signed: up/down) = tone drift, speech rate, hesitation live |
| `emotion_estimate.probs` (when present) | top-3 bars titled "Emotion estimate" |
| `features.pause_frac` | hesitation sparkline |
Do not display `stress_related_change` (alias). The existing `reason` string is already hedged and can be the caption.

## 2. Digital Twin (live state + timeline)
Twin = a running model of the person on the call (in the demo, the human playing the scammer): baseline learned (n/3), current delivery state (above), pressure level currently applied by our AI (1..3, from the scenario script), decisions so far (section 3), alerts. Timeline: x = call time; rows = AI turns (with pressure level), person turns (delivery change as colour), decision events as flags.

## 3. Decisions (operational)
`behaviour.decision_events` = `[{t, utterance_id, event}]` with `event` in `verification_requested`, `refused`, `complied_phrase` (keyword-based; show as "detected phrases", not as verdicts). C may replace with an LLM tag; keep the same shape.

## 4. End of call
At call end C does: `from detectors.session_signals import analyse; report["behaviour"] = analyse(report, pressure={interviewer_utterance_id: level})` before saving the report. Summary panel reads `report["behaviour"]`: `tone_drift`, `speech_rate`, `hesitation`, `response_latency_s`, `recovery_latency` (status `recovered | not_recovered_in_call | no_peak_over_threshold`), `interaction`, `delivery_change_by_pressure_level`.

## 5. Credential
After saving the report: `scripts/credential.py` functions `issue(report, decisions, key_path)` and `verify(cred, report)` (needs `cryptography`; add it to backend deps). Write `data/reports/<id>.credential.json`; serve it at `GET /api/credential/<id>` (C's `live_api.py`). UI: "Download credential" and a "Verify" link to a copy of `docs/verify.html` (copy it into `frontend/public/verify.html`; it is self-contained, no backend call). Show the issuer `did:key` and the claims text verbatim. The issuer key is `data/issuer.key` (never commit; create once).

## 6. Enabling the emotion probe
`EMOTION_PROVIDER=wavlm` in `.env` (needs `data/models/emotion_probe.npz`, made by `scripts/train_emotion_probe.py`; loads WavLM-base-plus, ~380 MB, first call slower). Off by default; the UI must handle `emotion_estimate: null`.

## 7. Emotion estimate: one practical tip
It misfires on ordinary calm speech (labels it disgust/sad), so keep it out of the verdict and out of the headline numbers; show it as a side bar. The delivery gauge, pressure timeline, decisions and credential carry the story.

## 8. From the two-stage notebook model (2026-10-10; NOT in the backend payloads yet)
Demo: scam-call simulation: a **human plays the scammer**, our AI pushes back and applies pressure (e.g. as the bank agent asking verification questions); the twin shows the scammer. If C integrates `assess_call` output, `signal_timeline[]` is the primary feed: per turn `signals` (`pitch_st_median`, `pitch_st_spread`, `speech_rate_wps`, `pause_frac`, `filler_rate`, `loudness_db`, `voiced_frac`, ...) and `delta_vs_own_earlier_turns` (same keys) = tone drift, speech rate and hesitation rows; response latency from section 4. `deception_assessment` is optional and secondary: if shown, label it "possible reading (uncalibrated model score)", list the alternatives, link the evidence turns, never "lying", never a verdict, and keep it out of the credential's claims. Bluff and mismatch return `insufficient_evidence` in this run.
