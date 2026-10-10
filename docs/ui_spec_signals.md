# UI spec for the signals, Digital Twin and credential (V to C)

Everything below already exists in the backend payloads. Wording rule everywhere: **"change vs this person's earlier delivery"**, never stress, lying, honesty or skill. Every number carries its `calibration_status` (always `not_established`) as a small "uncalibrated" tag.

## 1. Live (per utterance, from `signal` events with `signal == "prosody"`, `details`)
| Key | Show as |
|---|---|
| `status` | `building_baseline` -> "learning this person's normal (n of 3)"; `insufficient_evidence` -> grey "not enough clear audio"; `ok` -> live values |
| `delivery_change` (0..1 or null) | gauge "Change vs earlier delivery"; null = no gauge |
| `delivery_markers` (strings) | chips under the gauge, max 3 |
| `z` (pitch, spread, loudness, rate, pauses) | five small bars "vs own baseline" (signed: up/down) = tone drift, speech rate, hesitation live |
| `emotion_estimate.probs` (when present) | top-3 bars titled "Acted-emotion estimate (research probe)" |
| `features.pause_frac` | hesitation sparkline |
Do not display `stress_related_change` (alias). The existing `reason` string is already hedged and can be the caption.

## 2. Digital Twin (live state + timeline)
Twin = a running model of the person on the call: baseline learned (n/3), current delivery state (above), pressure level currently applied by our AI (1..3, from the scenario script), decisions so far (section 3), alerts. Timeline: x = call time; rows = interviewer turns (with pressure level), person turns (delivery change as colour), decision events as flags.

## 3. Decisions (operational)
`behaviour.decision_events` = `[{t, utterance_id, event}]` with `event` in `verification_requested`, `refused`, `complied_phrase` (keyword-based; show as "detected phrases", not as verdicts). C may replace with an LLM tag; keep the same shape.

## 4. End of call
At call end C does: `from detectors.session_signals import analyse; report["behaviour"] = analyse(report, pressure={interviewer_utterance_id: level})` before saving the report. Summary panel reads `report["behaviour"]`: `tone_drift`, `speech_rate`, `hesitation`, `response_latency_s`, `recovery_latency` (status `recovered | not_recovered_in_call | no_peak_over_threshold`), `interaction`, `delivery_change_by_pressure_level`.

## 5. Credential
After saving the report: `scripts/credential.py` functions `issue(report, decisions, key_path)` and `verify(cred, report)` (needs `cryptography`; add it to backend deps). Write `data/reports/<id>.credential.json`; serve it at `GET /api/credential/<id>` (C's `live_api.py`). UI: "Download credential" and a "Verify" link to a copy of `docs/verify.html` (copy it into `frontend/public/verify.html`; it is self-contained, no backend call). Show the issuer `did:key` and the claims text verbatim. The issuer key is `data/issuer.key` (never commit; create once).

## 6. Enabling the emotion probe
`EMOTION_PROVIDER=wavlm` in `.env` (needs `data/models/emotion_probe.npz`, made by `scripts/train_emotion_probe.py`; loads WavLM-base-plus, ~380 MB, first call slower). Off by default; the UI must handle `emotion_estimate: null`.

## 7. Known behaviour of the emotion probe (measured 2026-10-10)
Latency about 110-155 ms per utterance after a 4.5 s first load. It is in-sample on RAVDESS (trained on all 24 actors), so near-100% confidence there means nothing. On neutral read audiobook speech (LibriSpeech) it returned "disgust 0.45 / angry 0.42" and "sad 0.40 / calm 0.34": it over-reads acted categories on ordinary speech. So: show it only as a labelled research probe, never feed it to fusion or to the verdict, and do not describe it as what the person feels.
