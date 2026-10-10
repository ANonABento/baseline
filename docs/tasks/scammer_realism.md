# Task: make the AI scammer believable (research + rewrite the scenarios)

**Status:** DONE in code (scenarios + slow-burn phases in `backend/caller/personas.py`). Not done: the web research note `docs/research/scam_tactics.md`; scenarios were written from known FTC / UK Finance patterns.

## Problem
In role `client`, the visitor is the bank's customer and an AI fraudster calls them. The fraudster is obvious within one or two turns: it states the problem, demands the code, and pushes urgency right away. Real scammers build trust first.

We want a **mix**:
- Two or three obvious, pushy scams. These are quick wins and show Baseline flagging fast.
- Three or four **slow-burn** calls where, for the first several turns, neither the visitor nor an observer could tell it's a scam.

The fictional bank is **First City Bank** (`BANK_NAME` / `BANK_SHORT` in `backend/caller/personas.py`).

## Where the code is
- `backend/caller/personas.py`:
  - `client_scenarios()` (the `Scenario` dataclass: label, brief, summary, goals, tactics, openers, stub_lines, callee, claims_customer, clone_voice)
  - `fraudster_prompt()`, `SIM_FRAME`, `STYLE_RULES`
- The LLM is small and local: `qwen3.5:4b` on the Mac, `qwen3.5:27b` on the GPU box. Prompts must be **short and concrete**: phases plus two or three example lines each, not essays.
- The frontend references these scenario ids:
  - `frontend/src/pages/Lobby.tsx` (labels map)
  - `frontend/src/pages/Room.tsx` (`callerClaim()`)
  - `frontend/src/lib/mockScripts.ts`

  Keep the existing ids (`fake_bank`, `grandchild`, `irs`, `tech_support`) working. If you add ids, add their labels in `Lobby.tsx` and a `callerClaim` case in `Room.tsx`.

## Step 1: research (save to `docs/research/scam_tactics.md`, with sources)
How real phone scams run in 2024–2026:
- **Bank impersonation, "fraud department":**
  - spoofed caller ID
  - "Did you make a $X purchase at Y?"
  - quoting real partial data (last 4 digits, address)
  - "We'll never ask for your PIN" reassurance
  - case or reference numbers, transfer to a "supervisor"
  - the code "to reverse/cancel the transaction"
  - "safe account" transfers
  - "hang up and call the number on your card", with the line kept open
- **Bank-employee investigation:** "a teller is involved, don't tell anyone at the branch".
- **Amazon/Apple order or refund**, Medicare/benefits, utility shutoff.
- **Grandparent / voice clone**, with a second "lawyer" or "officer" voice; tech support.

Capture the arc: **rapport → legitimacy → problem → urgency → ask → objection handling**, and concrete lines scammers actually use.

Sources: FTC consumer alerts, FBI IC3, UK Finance, bank fraud pages, Which?, news, scam-baiter call transcripts.

## Step 2: rewrite the scenarios
- Add `pace: "fast" | "slow"` to `Scenario`, plus optional staged phases.
- **Slow scenarios:** `fraudster_prompt` gets explicit phases.
  1. **Rapport and legitimacy** (about 4–6 turns). Be genuinely helpful. Confirm details. Give a case number. Pre-empt red flags by echoing real bank advice ("we'll never ask for your PIN or password"). **Never ask for money or codes in this phase.**
  2. **The problem.** Something "found" while helping.
  3. **The ask**, framed as protecting them.
  4. **Objections.** Answer calmly and plausibly, offer "verification", apply soft pressure, and only escalate urgency late.
- **Fast scenarios** stay pushy, but sound more natural.
- **Suggested new slow ones:**
  - `fraud_dept_slow`: a very convincing First City fraud team call. It starts by confirming a "suspicious login", walks through recent transactions, gives a case number, and only late asks for the "verification code we just sent to reverse it".
  - `bank_investigation`: First City "security" asks for help catching a dishonest employee, and wants the customer to withdraw cash or move funds as "bait". Secrecy is part of the script.
  - `amazon_refund`: an order confirmation call that becomes a refund, then an "overpayment".
- **Improve the existing four:**
  - `fake_bank` can stay as the obvious version.
  - `grandchild`: add a hand-off to the "lawyer".
  - `irs` stays obvious.
  - `tech_support`: slower.
- **For every scenario:**
  - update openers, plus a one-line `brief` and `summary` (shown at the end of the call)
  - update `stub_lines`, the offline fallback script. Slow ones get 8–10 lines that build up.
- **Keep:**
  - `SIM_FRAME`, the authorized-training framing
  - `STYLE_RULES` (short phone turns, TTS-friendly, under 35 words)
  - everything fictional

## Step 3: test
- Run `uv run --project backend pytest -q tests` and fix tests that assert old wording.
- If Ollama is running, run `make` targets or `scripts/` to smoke-test a slow scenario for about 8 turns.
- Check the scammer doesn't ask for the code or money before phase 3.

## Don't touch
`backend/caller/live_call.py`, `backend/settings.py`, `backend/segmenter.py` (separate task: `docs/tasks/turn_taking.md`).

## Out of scope (still being decided)
Game-over / win-lose detection, hiding the scenario in the lobby, genuine (non-scam) calls, scammer-mode changes. If cheap, leave hooks for these: a `pace` field, and a `payload` description of what counts as "the victim gave it up".
