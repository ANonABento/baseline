# Action plan: pressure simulation to a deliverable (2026-10-10)

Submission deadline: Sat 2026-10-10 09:00 (MentorMates); finals 12:00 to 14:00. "Done when" is a check you can run or see. Items marked **Dae** need a person at the keyboard or a decision.

## Done in code (software verified, not science)
- Digital Twin and credential on **every** call (roles client and scammer; the separate pressure simulation was removed): your own delivery is measured live (client: `twin_det` on your turns; scammer: the pipeline's prosody detector), pressure levels 1 to 3 from the AI scammer in the client role, decisions, `behaviour` in the report, Ed25519 credential at `/api/credential/<id>`, issuer at `/api/issuer`.
- Caller prompt: reacts to what you said, asks follow-ups, recent lines fed back to avoid repeats; Nebius `gpt-oss-120b` by default in `make dev-live`; whisper-large-v3-turbo when cached.
- Twin panel in the live room and the report; credential panel; `verify.html`.
- Tests: backend 298 passed, frontend 41 passed, type-check and build clean.

## Do in this order
| # | Owner | Task | Done when | Time |
|---|---|---|---|---|
| 1 | Dae | `make dev-live` and `make dev-frontend`; take one 2-minute "Pressure simulation" call with the real mic, speaking calmly for 3 turns, then fast and loud | Twin shows baseline 3 of 3, pressure reaches 2 then 3, "Largest change" rises, report page shows the summary | 15 min |
| 2 | Dae | If Ollama is slow or down: set `CALLER_LLM_PROVIDER` to the Nebius/NVIDIA preset in `.env`, or accept scripted lines | AI replies react to what you said | 10 min |
| 3 | Dae | Click through: Lobby, call, hang up, report, Download credential, open `/verify.html`, paste it, see VALID; edit one character, see INVALID | both outcomes seen on screen | 10 min |
| 4 | Dae | Note anything broken in layout (Twin panel on small screen, ended dialog) and send it to Claude | list of issues | 10 min |
| 5 | Claude | Fix issues from 4; add an LLM decision tagger with the same output shape (keyword fallback) only if time remains | tests pass | 30 min |
| 6 | Dae | Take 5 to 10 real calls (vary calm vs pressured delivery); keep the report ids | `data/reports/` has them | 30 min |
| 7 | Claude | Script over those reports: per-call per-turn latency, baseline reached or not, max |z| by pressure level, a small table in `results/` | table exists, N stated, exploratory label | 20 min |
| 8 | Dae | Record the backup video of one clean call (screen + audio) | video file saved before 08:30 | 15 min |
| 9 | Dae | Publish the issuer: call `GET /api/issuer`, paste the DID into README and the pitch slide | DID in README | 5 min |
| 10 | Dae | Commit and push on `v/voice-model-plan`; check `frontend/public/verify.html` and `backend/credential.py` are included | `git status` clean | 10 min |
| 11 | Dae | Public URL if wanted (Replit per the master plan); otherwise demo from the laptop on its own network | URL opens `/call` or decision to demo locally | 45 min or skip |
| 12 | Dae | Rehearse the demo twice with `docs/pitch_twin_credential.md` | 3-minute run, no restarts | 20 min |

## Cut list (not before the deadline)
- Loading `baseline_mm.pt` / `baseline_brief_quick.pt` into the app. The quick checkpoint has no results, so say "z-scores against the person's own baseline plus an emotion probe", not "fine-tuned model".
- Accounts, identity, key rotation, revocation, hosted verifier.
- More than one concurrent call (`MAX_CONCURRENT_CALLS` is 1).
- Tuning detector thresholds (change vs own baseline needs sustained change in 2+ features; I did not alter it).

## Risks to watch
- Short or monotone calls show a gauge of 0. The "Largest change" row still moves; script the demo call with a clear shift.
- The persona LLM falling back to scripted lines.
- Emotion probe mislabels calm speech; it is a side bar only.
