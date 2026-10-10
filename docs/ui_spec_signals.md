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

## 5. Credential (implemented 2026-10-10)
`backend/credential.py` (`issue`, `verify`, `issue_for_report`, `load_credential`; CLI wrapper `scripts/credential.py`; `cryptography==50.0.2` is a backend dependency). `LiveCall.end` (role `candidate`) writes `report["pressure"]` and `report["behaviour"]`, saves the report, then signs the SAVED report and writes `data/reports/credentials/<id>.json`; `GET /api/credential/<id>` serves it. UI: `frontend/src/components/Credential.tsx` shows the issuer `did:key`, report SHA-256 and claims text verbatim, "Download credential" and "Verify offline" (`frontend/public/verify.html`, a copy of `docs/verify.html`; keep the two identical). The issuer key is `data/issuer.key` (never commit; `*.key` is gitignored).

## 5b. Where the Twin renders (implemented)
`frontend/src/lib/twin.ts` (pure view-model, tests in `frontend/tests/twin.test.ts`) -> `components/Twin.tsx` (`TwinPanel`, used in the live `Room` for role `candidate` and in the `Report` page). Live `pressure` and `decision` WebSocket messages feed `SessionState.pressure/decisions`.

## 6. Enabling the emotion probe
`EMOTION_PROVIDER=wavlm` in `.env` (needs `data/models/emotion_probe.npz`, made by `scripts/train_emotion_probe.py`; loads WavLM-base-plus, ~380 MB, first call slower). Off by default; the UI must handle `emotion_estimate: null`.

## 7. Emotion estimate: one practical tip
It misfires on ordinary calm speech (labels it disgust/sad), so keep it out of the verdict and out of the headline numbers; show it as a side bar. The delivery gauge, pressure timeline, decisions and credential carry the story.

## 8. From the two-stage notebook model (2026-10-10; NOT in the backend payloads yet)
Demo: scam-call simulation: a **human plays the scammer**, our AI pushes back and applies pressure (e.g. as the bank agent asking verification questions); the twin shows the scammer. If C integrates `assess_call` output, `signal_timeline[]` is the primary feed: per turn `signals` (`pitch_st_median`, `pitch_st_spread`, `speech_rate_wps`, `pause_frac`, `filler_rate`, `loudness_db`, `voiced_frac`, ...) and `delta_vs_own_earlier_turns` (same keys) = tone drift, speech rate and hesitation rows; response latency from section 4. `deception_assessment` is optional and secondary: if shown, label it "possible reading (uncalibrated model score)", list the alternatives, link the evidence turns, never "lying", never a verdict, and keep it out of the credential's claims. Bluff and mismatch return `insufficient_evidence` in this run.

## 9. Implementation status vs this spec (code audit, 2026-10-10; read-only, nothing run)
Live path today: `Room.tsx` push-to-talk mic -> `WS /ws/session/{id}` -> `LiveCall` (scammer role analyses the human; AI lines `analyzed=False`) -> `transcript` / `signal` / `trust` / `alert` events -> `buildNotes` (`frontend/src/lib/notes.ts`).

| Spec item | Status | Evidence / gap |
|---|---|---|
| §1 live prosody panel (gauge, z bars, markers, pause sparkline, "learning normal n of 3") | partial (2026-10-10) | `frontend/src/components/Signals.tsx` shows the latest pitch z (or "learning baseline") per turn; gauge/z bars/sparkline not built; `details.z` / markers are never read in `frontend/src`; prosody confidence is capped at 0.25 (`backend/detectors/prosody.py:288`) but the UI and fusion need >= 0.3 (`notes.ts:39`, `analysis.ts:15`, `settings.py:98`), so prosody never appears live |
| Tone drift, speech rate, pauses | **live** (2026-10-10) | `Signals.tsx` panel in `Room.tsx`, fed by the `behaviour` WS event; `voice_state.py` (z, `rate_proxy`, `pause_frac`) |
| Fillers, hedging, talk-over, verification attempts, refusals, response latency, de-escalation latency | **live** (2026-10-10) | `LiveCall._emit_behaviour` runs `session_signals.analyse()` after every analysed transcript/prosody event and sends `{"type":"behaviour", ...}`; decisions shown as chips |
| Response latency correctness | **fixed** (2026-10-10) | visitor audio turns are mapped from mic-sample time to call time (`LiveCall._mic_to_call_time`); was: human utterance times come from fed-sample counts (push-to-talk), AI/typed lines from wall clock (`segmenter.py:73`, `live_call.py:350,425,481`), so latency/talk-over would be wrong |
| §2 Digital Twin page, pressure levels 1..3 | missing | no twin component; bank-agent persona has no escalation (`personas.py`) |
| §3 decisions during the call, §4 `report["behaviour"]` | **live / saved** (2026-10-10) | keyword decision events stream live; `build_report` now sets `behaviour` |
| §5 credential from the app | CLI only | `scripts/credential.py` works; no `cryptography` dependency, no `/api/credential`, no Download/Verify UI, `verify.html` not in `frontend/public/` |
| §6 emotion probe | off | no `data/models/emotion_probe.npz`; `EMOTION_PROVIDER` read from `os.environ`, so `.env` alone does not enable it |
| §8 notebook model | not wired | no inference wrapper for new audio; feature keys/units differ (`pitch_st_median` re 100 Hz vs backend `f0_median_st`) |
| Role copy for the scammer demo | mismatched | verdict strip / "Say this" advice, "The caller was <AI persona>" overlay, Report and Landing copy assume a bank agent/customer view; Lobby role defaults to random |
| Wording rule (no "stress"/"pressure" as a label) | mismatched | "Caller sounds under pressure" (`fusion.py:45,234`), "Pressure" labels (`notes.ts:30`, `analysis.ts:27`) |
| Spoken input on Linux | stub | `mlx-whisper` is macOS-only; Linux falls back to stub STT (typed text works); demo needs the Mac |

Order of work for the demo: (1)-(2) done 2026-10-10 (live signal panel, utterance clock, `behaviour` WS event); next: (3) Twin panel in `Room.tsx` with AI pressure levels; (4) credential endpoint + Download/Verify; (5) scammer-role copy and neutral wording; (6) disable silent mock fallback, real STT + enrolment on the demo Mac; (7) emotion probe; (8) notebook-model inference wrapper.
