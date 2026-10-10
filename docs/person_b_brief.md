# Person B Brief: App / Product / Pitch

Hand this file to your Claude Code session: "Read docs/person_b_brief.md and docs/baseline_master_plan.md, then start on task 1."

## Context in 30 seconds
Baseline is a real-time co-pilot for **bank call-center agents**. It flags voice-clone account takeovers and customers being coached by scammers. We **sell to banks, protect the innocent.** The backend skeleton works end to end (commit `e468ae9`). Person A (audio/ML) is swapping the stub STT / speaker / spoof detectors for real models on a separate branch.

## You own
`backend/providers/llm_*`, `backend/detectors/fraud.py`, `backend/kb/`, `backend/fusion.py`, `backend/app.py`, `frontend/`, the pitch, and the MentorMates submission.

**Don't change without telling A:** `backend/events.py` (event schema) and `DetectorResult`. Person A owns `detectors/{spoof,speaker,prosody}.py`, `segmenter.py`, `providers/stt_*`, `scripts/`, `data/`.

## Setup
```bash
git clone https://github.com/ANonABento/baseline.git && cd baseline
# install uv: curl -LsSf https://astral.sh/uv/install.sh | sh ; Node 20+ needed
make setup && make test          # 58 tests should pass
cp .env.example .env              # add NEBIUS_API_KEY; confirm LLM_BASE_URL / LLM_MODEL for your account
make dev-backend                  # terminal 1
make dev-frontend                 # terminal 2, open the printed URL, pick a clip, press Start
```

## Tasks, in order
1. **Real LLM fraud analyzer:** get Nebius working (check the model id/base URL). Tune the prompt on the `data/demo/*.txt` transcripts. Output must parse every time (the parser tests already exist), and stay under ~1.5 s per utterance.
2. **New fraud signals** (from the competitor research, see plan §1 "Borrowed from Substrata"):
   - **Verification evasion:** the caller dodges or deflects identity questions ("I don't have that on me, can we just do this quickly"). Add it to the playbook and the LLM prompt.
   - **Coached customer:** cues of a third party directing the customer ("he says I need to...", "they told me not to tell you"). Add to the playbook.
3. **Dashboard polish** (a judge should understand it in 5 seconds):
   - Customer profile panel ("Margaret Chen · voice baseline enrolled ✓").
   - Four signal cards: Voice Match / Synthetic Audio / Fraud Pattern / Pressure. Each shows a score, a one-line *why*, and its evidence (quoted transcript line + citation link).
   - Big Trust Score.
   - Red takeover card with the **suggested agent action** when the alert is high.
   - **Timeline:** show *which line* triggered each signal (click a flag → highlight the transcript line).
4. **Proof strip:** a chart of `results/history.csv` (accuracy over the night) + per-utterance latency + "runs on one MacBook".
5. **Live mic:** test it in Chrome; fix whatever breaks.
6. **Verify the playbook source URLs** actually resolve before we cite them on stage.
7. **Pitch:** 3-minute script + ~5 slides (problem → demo → proof → who pays → close). See plan §5. Draft the MentorMates submission text early.

## Sync points with A
- **10 PM:** a real clip replays with a real transcript + fraud flags.
- **1 AM:** all-real end-to-end run; delete `data/demo/takeover_clone.meta.json` (the stub hint).
- **4 AM:** decide cuts.
- **6 AM:** feature freeze.
- **Submit by 8:30 AM.**
