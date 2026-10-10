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
Twin = a running model of the person on the call: baseline learned (n/3), current delivery state (above), pressure level currently applied by our AI (1..3, from the scenario script), decisions so far (section 3), alerts. Timeline: x = call time; rows = interviewer turns (with pressure level), person turns (delivery change as colour), decision events as flags.

## 3. Decisions (operational)
`behaviour.decision_events` = `[{t, utterance_id, event}]` with `event` in `verification_requested`, `refused`, `complied_phrase` (keyword-based; show as "detected phrases", not as verdicts). C may replace with an LLM tag; keep the same shape.

## 4. End of call
At call end C does: `from detectors.session_signals import analyse; report["behaviour"] = analyse(report, pressure={interviewer_utterance_id: level})` before saving the report. Summary panel reads `report["behaviour"]`: `tone_drift`, `speech_rate`, `hesitation`, `response_latency_s`, `recovery_latency` (status `recovered | not_recovered_in_call | no_peak_over_threshold`), `interaction`, `delivery_change_by_pressure_level`.

## 5. Credential (implemented 2026-10-10)
`backend/credential.py` (`issue`, `verify`, `issue_for_report`, `load_credential`; CLI wrapper `scripts/credential.py`; `cryptography==50.0.2` is a backend dependency). `LiveCall.end` (role `candidate`) writes `report["pressure"]` and `report["behaviour"]`, saves the report, then signs the SAVED report and writes `data/reports/credentials/<id>.json`; `GET /api/credential/<id>` serves it. UI: `frontend/src/components/Credential.tsx` shows the issuer `did:key`, report SHA-256 and claims text verbatim, "Download credential" and "Verify offline" (`frontend/public/verify.html`, a copy of `docs/verify.html`; keep the two identical). The issuer key is `data/issuer.key` (never commit; `*.key` is gitignored).

## 5b. Where the Twin renders (implemented)
`frontend/src/lib/twin.ts` (pure view-model, tests in `frontend/tests/twin.test.ts`) -> `components/Twin.tsx` (`TwinPanel`, used in the live `Room` for role `candidate` and in the `Report` page). Live `pressure` and `decision` WebSocket messages feed `SessionState.pressure/decisions`.

## 6. Enabling the emotion probe
`EMOTION_PROVIDER=wavlm` in `.env` (needs `data/models/emotion_probe.npz`, made by `scripts/train_emotion_probe.py`; loads WavLM-base-plus, ~380 MB, first call slower). Off by default; the UI must handle `emotion_estimate: null`.

## 7. Emotion estimate: one practical tip
It misfires on ordinary calm speech (labels it disgust/sad), so keep it out of the verdict and out of the headline numbers; show it as a side bar. The delivery gauge, pressure timeline, decisions and credential carry the story.
