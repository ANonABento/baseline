# Pitch notes: pressure simulation (Digital Twin + verifiable credential)

One line: a 3-minute high-pressure voice simulation that measures how a person's delivery and decisions change under pressure, shows it live on a Digital Twin, and issues a credential anyone can verify offline.

## Demo (3 min)
1. Lobby: pick "Pressure simulation". (10 s)
2. Call: three calm turns, Twin shows "learning normal 3 of 3". Pressure goes 1, 2, 3 as the caller escalates. Speak faster and louder, ask to verify, refuse. Point at the gauge, z bars, speech rate, response latency, pressure timeline, detected phrases. (90 s)
3. Hang up: report with tone drift, speech rate, hesitation, de-escalation latency, change by pressure level. (30 s)
4. Credential: download, open `/verify.html`, VALID; edit one character, INVALID. (40 s)

## Claims we can support (and the source)
- Signals are computed in real time from the person's own voice and compared with their first 3 turns: `backend/detectors/voice_state.py`, `session_signals.py`; known-answer tests in `tests/`.
- The credential is Ed25519 over the exact signed text, with a `did:key` issuer, verified offline in the browser: `backend/credential.py`, `frontend/public/verify.html`; tamper test passes.
- Runs on one laptop with local models.

## Claims we must not make
- That the signals measure stress, honesty, skill or suitability (calibration is `not_established`; no open dataset has stress ground truth).
- "Fine-tuned model" for the live signals (they are z-scores; only the emotion probe is trained, on acted speech).
- That it works on real phone audio or many speakers (no such test).

## Likely Q&A
- **Why z-scores, not a model?** No labelled stress data exists for this; comparing a person with their own baseline needs no label and works for any speaker. A trained model would be a hypothesis we could not validate tonight.
- **What does the credential prove?** Who signed which observations from one simulated call, and that the report was not changed. Not skill.
- **How would an employer use it?** As one structured, reproducible work sample next to interviews, with the candidate's consent, not as a score.
- **Bias?** Pitch and pace differ by voice, accent, microphone and noise. Comparing with the person's own baseline reduces but does not remove this; it needs testing across speakers before real use.
- **Path to adoption?** Scenario packs per role (support, banking, clinical triage), ATS integration, hosted verifier and key management, calibration studies with outcome data.
- **Scale?** Today one call at a time on a laptop; per-turn work is light (prosody took about 6 ms once on a 2.7 s demo clip on this MacBook, a single unrepeated measurement; STT and the LLM were not timed).
