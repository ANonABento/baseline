# Task: redesign the role-play (scammer ↔ the bank's client), the lobby, the in-call cheat sheet + bug fixes

**Owner:** next agent · **Size:** about 2–3 hours, work through the sections in order · **Deadline:** submission at 9:00 AM, Oct 10; finals 12–2 PM
**Read first:** `docs/tasks/scammer_realism.md` covers the scenario rewrite. Do it before or with section 2 here, because both edit `backend/caller/personas.py`.

## Product framing (why this changes)
We sell Baseline to **banks**. It's a verification and fraud engine that protects the **bank's clients** from scammers. It runs on the client's phone through the bank's app, and in the call center. The demo is **never** "call the bank pretending to be Kevin".

There are only two sides in a demo call: **a scammer** and **a First City client**. The visitor picks a side, and the AI plays the other one:

| Visitor plays | AI plays | Baseline protects |
|---|---|---|
| **The client** ("Get a call"): a random person receives a call | a scammer, from `client_scenarios` | the visitor |
| **The scammer** ("Make a call"): the visitor calls a random person with an agenda | a **random First City client persona** who doesn't know it's a scam | the AI persona |

## 1. Lobby (`frontend/src/pages/Lobby.tsx`)
- **"Random" goes first in the role list and is the default.** Set the initial `useState` role to `"random"`. The backend already accepts `random`; check `backend/sessions.py`.
- Role labels and hints:
  - Random: "Surprise me: you might get a scam call, or you might be the scammer"
  - **Get a call**: "You're a First City client. Someone calls you."
  - **Make a call**: "You're the scammer. Call a First City client and try to get what you came for."
- Remove all copy about calling First City or pretending to be Kevin. That includes the `ROLES` scammer hint and the `config__sub` paragraph.
- For "Make a call", the scenario picker becomes **"Your target / agenda"**, with a "Surprise me" option first and as the default.
- Keep the internal role ids (`client`, `scammer`), so the backend, contract and tests don't change. Only the copy changes.

## 2. Backend: the scammer role, AI as the victim (`backend/caller/personas.py`)
- Replace `bank_agent_prompt` / Jordan (`BANK_AGENT_*`) with **victim personas**: a few random First City clients, each with a name, age, job, temperament, how trusting they are, what they'd give up, and their tells.
  - Example: Margaret, 74, a retired teacher. Polite and lonely, trusts "the bank", but gets suspicious if rushed.
  - Example: Dev, 29, a nurse on shift. Busy and distracted, wants it over fast.
  - Example: Linda, 52, a small-business owner. Skeptical, asks for callback numbers.
- **Victim prompt:**
  - You're a real person answering an unknown call.
  - Answer the phone naturally ("Hello?").
  - Don't volunteer secrets, but you are human: a good, patient scammer *can* get you if they build trust.
  - Ask normal questions.
  - Hang up (end the turn with an exact phrase like "I'm going to hang up now") if it gets too pushy or obviously fake.
- **Baseline's warnings reach the victim.** When Baseline intervenes on the victim's side, the victim reacts: hesitates, asks the scammer to verify, or hangs up. Look at how `backend/caller/intervention.py` speaks to the visitor in the client role, and mirror it into the victim's brain context, e.g. `brain.add_system("Your bank app just warned you: ...")`.
- **Scammer scenarios become agendas against a person.** Each one needs:
  - `target` (the persona id or "random")
  - `goal` (what counts as winning: the OTP read out, the gift card numbers, an agreed transfer, a remote-access code)
  - `cover_story`
  - `steps` (3–5 suggested beats)
  - `lines` (example openers or lines)
  - `objections` (likely pushback, and how scammers usually answer it)
  - `red_flags_baseline_watches` (to show what will get them caught)

  Reuse the research and arcs from the scammer-realism task, so the agendas mirror the client scenarios (bank fraud dept, grandchild, IRS, tech support, Amazon refund, and so on).
- Send the agenda to the frontend in the session `config` / call-start payload. Extend the TypeScript `contract.ts` / `types.ts` to match.

## 3. In-call cheat sheet overlay, scammer side only (`frontend/src/pages/Room.tsx`)
- A collapsible panel visible during the call, titled "Your agenda". It shows:
  - the target (name, one-line profile)
  - the goal, the cover story and the beats as a checklist
  - two or three suggested lines, objection → comeback, and "What Baseline is watching for"
- Keyboard toggle (e.g. `C`). Don't steal Space, which is push-to-talk.
- It must not cover the push-to-talk button or the transcript on a laptop screen. It must work at phone width (16px gutter, no horizontal scroll).
- Match the existing minimal dark UI (`index.css` tokens). Load the `frontend-design` skill.

## 4. Remove "Voice doesn't match enrolled customer"
This makes no sense now: nobody claims to be an enrolled customer. In the client role the AI caller is a stranger, and in the scammer role the visitor is a stranger.
- Backend:
  - Don't run speaker verification, or at least don't fuse it, unless the scenario has `claims_customer=True`. That's the grandchild voice clone, where the caller claims to be the victim's grandson; there the check should compare against the grandson's enrolled voice and the message should say that.
  - Check `backend/fusion.py` (`speaker` weight and reason text, `REASON_TEXT["speaker"]`) and `backend/pipeline.py`.
- Frontend: update copy in `lib/notes.ts:28`, `lib/mock.ts:292-309`, and `lib/mockScripts.ts:149` (mock mode).
- Synthetic-voice (spoof) detection stays: "This voice shows signs of being AI-generated." That is the honest voice story for the pitch.

## 5. Bug: push-to-talk clips words (`frontend/src/pages/Room.tsx:169-235`)
Symptoms: the start of speech is slightly delayed or lost, and words are cut off after releasing Space if not enough time has passed.
- **Start:** only frames captured *while holding* are sent, so the mic and worklet latency, plus people starting to speak as they press, eat the first syllable.
  - Fix: keep a ~300 ms ring buffer of recent PCM always, and flush it on `press()` before streaming.
- **End:** `TAIL_MS = 600` keeps sending after release, but:
  - (a) Check whether audio still in flight in the worklet or `startMic` (`frontend/src/mic.ts`) is dropped when the gate closes. Consider raising the tail to ~800 ms.
  - (b) **Important:** the backend now has an end-of-turn hold (`turn_end_silence_ms` 800 + `turn_unfinished_extra_ms` 1100, commit 006a45c, `LiveCall._hold_for_end_of_turn`). With push-to-talk, **release IS the end of turn**, so that hold only adds latency.
  - Add a client message, e.g. `{"type":"ptt","state":"up"}`, sent on release:
    - The backend force-closes the turn VAD segment after the tail (flush the segmenter).
    - It marks the next turn as final, so `_hold_for_end_of_turn` skips the wait.
    - Look at how `live_api.py` routes client JSON messages to `LiveCall`.
  - On `{"type":"ptt","state":"down"}`, keep the current barge-in behavior.
- Test manually: hold Space, say "one two three four five", and release right after "five". All five words should appear in the transcript, and the reply should come in under about 1.5 s.

## 6. Bug: the timeline curves are clipped (`frontend/src/components/Baseline.tsx`, `.room__timeline` in `index.css:537`)
The red spike curves are cut off at the top and bottom on Kevin's laptop.
- `.room__timeline .baseline { height: 4.5rem }`, and the canvas draws spikes taller than the box (plus the `agitation` wobble).
- Fix: compute the spike amplitude from the canvas height with padding (max amplitude ≈ 0.42 × H), and/or allow `overflow: visible` with vertical padding on `.room__timeline`.
- Check at 1280×800, 1440×900, and phone width.

## Still open (Kevin to decide; don't build unless told)
- **Game over and win/lose:**
  - The client side loses when they hand over the code or money, and wins when the scammer gives up or they hang up on a scam.
  - The scammer side wins when the victim complies, and loses when the victim hangs up or Baseline gets them to hang up.
  - Add a time cap of about 4 minutes.
  - The reveal shows "Baseline flagged at 0:42 vs you at 2:10".
- Mixing genuine (non-scam) calls into "Get a call".

## Done when
- `uv run --project backend pytest -q tests` is green. Update tests that referenced Jordan or the bank agent, e.g. `tests/test_live.py`.
- `cd frontend && npm run build` passes.
- A manual call in each role works end to end.
