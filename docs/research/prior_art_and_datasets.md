# Baseline: Prior Art, Datasets & Research (open source / academic)

> Compiled 2026-10-09 for the Baseline hackathon. Scope: open-source and academic prior art, datasets, LLM-scam research, agent-assist UX, drop-in libraries. Commercial competitors (Pindrop, Pixel, Reality Defender) and market stats are in a separate doc.
> Sizes and schemas below were checked live against the Hugging Face datasets-server API / GitHub API on 2026-10-09 unless marked *(unverified)*.

---

## 1. Open-source / hackathon prior art

Pattern across everything found: **almost every project is a consumer "scam score" app** (Twilio proxy number or phone listener, then STT, then an LLM, then a red/yellow/green verdict). Nobody open-source fuses *enrolled voiceprint + synthetic-voice detection + script analysis* for the **bank agent's** screen. Our differentiation is real; the generic "LLM reads transcript, says SCAM 87%" demo has been done many times.

| Project | What it did | Stack | Impressive | Weak |
|---|---|---|---|---|
| **FraudFence** ("Les Détectives"), [Julius Baer jbswisshacks 2024 winner](https://www.juliusbaer.com/en/insights/company-insights/behind-the-scenes/jbswisshacks-2024-making-it-to-show-whos-faking-it/) | Bank challenge: "spot deepfake calls and verify client identity." Real-time transcription + translation, **indicators shown on the relationship manager's dashboard while the client is on the line** | not public | Closest prior art to Baseline, and it **won a bank-sponsored hackathon**, which validates the framing (agent-side dashboard, not consumer app) | No public code found; detection method not described in what we could access *(details from search snippet; page 403'd)*. Our edge: enrolled voiceprint + spoof + published eval numbers |
| **ShaScam**, [github.com/dariuskia/Shascam](https://github.com/dariuskia/Shascam) | Live call scam analysis via Twilio proxy number | Twilio, Google STT, Mixtral-8x7B | End-to-end on real phone calls; proxy numbers to handle consent | No eval numbers; README says "scarcity of quality spam call datasets"; single LLM verdict |
| **WatchDog**, [github.com/FadedBronze/StarterHacks](https://github.com/FadedBronze/StarterHacks) ("Most Promising", StarterHacks 2024) | Listens to calls, shows a live "scam score" for seniors | React/Tailwind/Framer Motion, Flask, phrase matching | Polished animated score UI won the prize | Keyword matching, so high FP risk; "high accuracy" claimed with no numbers |
| **FriendZone**, [github.com/Walnit/FriendZone](https://github.com/Walnit/FriendZone) (iNTUition 2024) | Against "guess who I am" scams: the proxy line makes first-time callers say their name, then GPT checks whether the caller later uses a **different name** or keeps asking "guess who" | Twilio, ngrok, Flask, GPT | **Narrow, checkable rule tied to one scam script** (identity consistency). Same idea as our "verification evasion" signal | Auto-hangup on an LLM decision is risky; consumer only |
| **Guardian Angel** ([AI Tinkerers hackathon, 1st place](https://portland.aitinkerers.org/hackathons/h_Xu4dbx3kfMs/entries/ht_59nCFqZrOQQ)) | Elder phone-scam protection: hybrid detection (FAISS retrieval of known scam snippets + Claude), live ElevenLabs transcription, and a **Tavus video-avatar that intervenes** | FAISS, Claude, ElevenLabs STT, Tavus | Retrieval of similar known-scam lines as evidence; a dramatic intervention moment for the demo | Avatar is a gimmick for an enterprise buyer; no deepfake-audio signal *(details from search snippet; page 403'd)* |
| **Phish Eye**, [github.com/krishnamodi29/phish-eye](https://github.com/krishnamodi29/phish-eye) (Gemini Live Agent Challenge, Mar 2026) | Screenshot / camera / pasted-transcript scam analyzer | Gemini 3.1 Pro, Flask, Cloud Run, Cloud TTS | Clean output contract: **SAFE / SUSPICIOUS / SCAM + red-flags list + action card** | "Call Guard" is paste-a-transcript, not live; no evaluation |
| **CallerIDK**, [devpost.com/software/caller_idk](https://devpost.com/software/caller_idk) | Banking fraud: flags deepfake voices live or in files, obfuscates sensitive data, logs suspicious calls | (page 403) | Same buyer as us (banks); adds PII masking | No visible metrics/placement |
| **FoiceDetect**, [devpost.com/software/foicedetect](https://devpost.com/software/foicedetect) | "How fake does this voice sound" + scam-response suggestions | Nebius AI, Modal | Pairs score with suggested response | Single signal (voice only) |
| **Catphish** (HackNC State, [Valkey blog](https://valkey.io/blog/victory-at-hackncstate/)) | Voice-based login that rejects a mismatched voice or an AI-generated response | Valkey (vector store) + voice embeddings | Speaker-verify + spoof as one gate, the same pair we use | Login gate, not live-call monitoring |
| **AssemblyAI tutorial**, [Detect scam calls with Go + Twilio](https://www.assemblyai.com/blog/detect-scam-calls-go-twilio) (Sept 2026) | Twilio Media Streams → WebSocket → streaming STT → **LLM pass at end of call** | Go, ~250 LOC | Minimal reference for phone-audio plumbing (8 kHz mu-law frames) | Post-call verdict, not real-time |
| **Central Bank of India Cybersecurity Hackathon 2025**, [problem doc](https://financialservices.gov.in/beta/sites/default/files/2025-10/Central-Bank-of-India.pdf) | App records 10 s call chunks → server STT + deepfake detection + diarization | n/a | Shows banks are actively asking for exactly this | 10 s chunk latency |

### Academic systems with demos
| System | What | Result | Takeaway for us |
|---|---|---|---|
| Shen et al., CHI'25 LBW, ["It Warned Me Just at the Right Moment"](https://arxiv.org/abs/2502.03964) | LLM judges the call after every turn; prompts RT (FRAUD/SAFE) vs UNC (adds UNCERTAIN) | RT recall 0.98-1.00 but **precision fell to 0.70-0.77** on synthetic sets with suspicious keywords; UNC lifted precision to 0.83-0.85, recall to ~0.90-0.98. UNC alerted at turn 10 (when ID was requested) vs RT at turn 6 | **Use a 3-state output (clear / watch / alert)**. "Payment"/"ID" in a benign rebooking call caused FPs. Alert timing is a UX trade-off: too early looks like "jumping to conclusions" |
| [Real-time fraud detection w/ RAG](https://arxiv.org/abs/2501.15290) (2025) | Streaming transcript + RAG over policy, checks for requests of private info | 97.98% acc / 97.44 F1 on **100 synthetic calls** | Policy-RAG with citations is a known pattern; small synthetic evals are the norm (we can beat that with an FP suite) |
| [ConvoSentinel (EMNLP'24)](https://github.com/lynneeai/ConvoSentinel) | Message-level "sensitive-info request" detector + retrieval of similar known SE snippets + conversation-level LLM verdict | Beats single-LLM baselines on SEConvo at lower cost | **Two-level design**: per-turn flags, then a conversation verdict. Retrieval of similar known scam lines = "evidence" |
| [Explainable agentic scam detector w/ summary memory](https://arxiv.org/abs/2607.11707) (2026) | Rolling summary memory over long conversations | 97.8% on ConScamBench-278, SUS 74.7 | **Rolling summary + last-N turns** keeps LLM latency flat as calls get long |
| [StreamFraudNet](https://arxiv.org/abs/2609.20223) (2026) | Scam detection from raw audio (frozen SSL encoder + RNN), no transcript | ROC-AUC 0.995; first prediction after 10 s, updates every 2 s | Audio-only works on controlled data, but early predictions are weak. Supports our "text + audio fusion" choice |
| [ICFD-31k (IJCAI'26)](https://www.ijcai.org/proceedings/2026/786) | Streaming-chunk labels + rationale at each 12 s | RoBERTa baselines | Report **time-to-detect**, not just accuracy |

### UX/demo ideas to borrow
- **Agent-side dashboard, not consumer app** (FraudFence won a bank hackathon with exactly this).
- **Verdict + red-flag list + action card** (Phish Eye) → our signal cards + "Suggested action".
- **Identity-consistency check** (FriendZone): the name/relationship/claim the caller gave earlier vs. now. A cheap, explainable LLM rule.
- **"Similar known scam" evidence** (Guardian Angel, ConvoSentinel): show the playbook entry/FTC example closest to the flagged line.
- **Three-state verdict with an explicit "watching" middle** (CHI'25 UNC prompt), which reduces FPs.
- **Time-to-alert as a headline metric** (ICFD-31k, CHI'25): "flagged at 0:41, before the wire request."

### What to avoid
- A single big "SCAM 87%" number with no evidence (WatchDog, most Devpost entries). Judges have seen it.
- Keyword triggers ("payment", "verify", "wire"), the #1 documented FP cause, especially in a *bank* call where those words are normal.
- Auto-actions (auto-hangup) on an LLM call. Keep the human agent in charge.
- Claiming accuracy from a 100% score on a tiny synthetic test (the BERT-on-Kaggle 100/100/100/100 pattern).
- Gimmicks that don't fit the enterprise buyer (avatars).

---
## 2. Datasets for evaluating the fraud/scam transcript analyzer (MOST IMPORTANT)

### TL;DR
- **No public English corpus of *real* bank-call account-takeover transcripts exists.** Every English scam-call set is either synthetic (LLM-generated) or from YouTube scam-baiters. Say this out loud in the demo: it is why we report numbers on several sets, including a held-out one we wrote ourselves.
- Synthetic sets are **easy** (LLMs hit ~95-100%). The real test is **false positives on benign calls that use the same scary words** ("verify", "wire", "payment", "your account"). Build the FP suite from real bank-style customer-service dialogues.
- Pull time: everything in "Tier 1" is < 50 MB and loads in < 1 min with `datasets.load_dataset(...)` or the parquet URL. No auth needed.

### Tier 1: pull tonight (English, small, permissive, instant)

| # | Dataset | What | Size | License | Format / schema | Pull |
|---|---|---|---|---|---|---|
| 1 | [BothBosu/scam-dialogue](https://huggingface.co/datasets/BothBosu/scam-dialogue) | Synthetic 2-party phone dialogues (Llama-3-70B), scam vs non-scam, 8 types: ssn, refund, support, reward, delivery, insurance, telemarketing, wrong-number. 50/50 balance | 1,600 (1,280 train / 320 test), ~2.3 MB, ~1.4k chars/dialogue | Apache-2.0 | CSV: `dialogue` ("caller: ... receiver: ..." one string), `type`, `label` (0/1) | `load_dataset("BothBosu/scam-dialogue")`, seconds |
| 2 | [BothBosu/multi-agent-scam-conversation](https://huggingface.co/datasets/BothBosu/multi-agent-scam-conversation) | Same idea but two LLM agents role-play, and the victim has a **personality** (trusting, greedy, confused, anxious, skeptical, aggressive, polite, distracted). Longer (median 2.4k chars, up to 13k). Non-scam includes plausible "appointment confirmation" calls, so it is a good FP test | 1,600 (1,280/320), 4.8 MB | Apache-2.0 | CSV: `dialogue` ("Suspect: ... Innocent: ..."), `personality`, `type`, `labels` | seconds |
| 3 | [BothBosu/single-agent-scam-conversations](https://huggingface.co/datasets/BothBosu/single-agent-scam-conversations) | Single-LLM version of #2 | 1,600, 2.4 MB | Apache-2.0 | CSV `dialogue,type,labels` | seconds |
| 4 | [BothBosu/youtube-scam-conversations](https://huggingface.co/datasets/BothBosu/youtube-scam-conversations) | **Real** scam calls transcribed from scam-baiter YouTube videos (tech support, etc.), with source link + channel | **20** calls, 56 KB | (no license tag; YouTube-derived, research use) | CSV: `dialogue` (newline turns), `type`, `call`, `link`, `channel`, `labels` | seconds. Use as the "real-world" sanity set |
| 5 | [Lakshan2003/customer_service_client_agent_conversations_40k_multi_task](https://huggingface.co/datasets/Lakshan2003/customer_service_client_agent_conversations_40k_multi_task) | Synthetic **benign** agent/client calls, many are banking ("thank you for calling Union Financial... may you please verify your identity"). **Best FP set**: full of verify/account/payment vocabulary with no fraud | 40,000, 46 MB | (no license tag on card, treat as research-only) | Parquet: `conversation` = list of `{speaker: agent/client, text}`, `num_turns`, `customer_sentiment` | ~30 s; sample 300 |
| 6 | [SEConvo (Zenodo 12170260)](https://zenodo.org/records/12170260), code: [lynneeai/ConvoSentinel](https://github.com/lynneeai/ConvoSentinel) | EMNLP 2024. 1,400 GPT-4-Turbo social-engineering conversations (fake recruiter / journalist / academic funding), with **message-level annotations** of which turn requests sensitive info. Not phone/bank, but the only set with per-message SE labels | 1,400 conversations; ~7 MB JSON | CC-BY-4.0 (data), MIT (code) | JSON: `annotated_train/test.json`, `unannotated_*` | `curl` 4 files, < 1 min |
| 7 | [flowxai/scamguardbench](https://huggingface.co/datasets/flowxai/scamguardbench) | EN/RO **message** (SMS/email/chat) benchmark, but its design is exactly what we want to copy: a `legit_confusable` subset (real bank OTPs, real "family send me money" texts) tagged by confusable class, a `hard` subset of paraphrases that avoid trigger words, and `tactics: [{tactic, evidence: verbatim substring}]` | 1,099 rows (598 standard, 346 legit_confusable, 122 suspicious, 33 hard) | Apache-2.0 | JSONL by config | seconds. Use `legit_confusable` + `hard` (EN only) as an extra FP/robustness check, and copy its schema for our eval file |

### Tier 2: useful, but bigger / non-English / restricted

| Dataset | What | Size | License | Notes |
|---|---|---|---|---|
| [ICFD-31k](https://huggingface.co/datasets/rishia2220/icfd-31k) ([code](https://github.com/SPELLAILab/ICFD-31k), [IJCAI 2026 paper](https://www.ijcai.org/proceedings/2026/786)) | 31k synthetic Indian fraud calls, 10 categories (incl. `bank_payment_fraud`), **streaming chunk labels** (verdict at 12 s, 24 s, ...) with a "slow-thinking" rationale per chunk, plus a `cross_domain` split | 1.07M chunk rows, 49 MB parquet; not gated | "other" on HF; MIT code | **Mostly Hinglish** (e.g. "Namaste Vikram ji, main Barclays Bank se bol raha hoon"), so weak for English accuracy, but the **schema is the gold standard for "when did the alert fire"** (time-to-detect). Filter `domain=bank_payment_fraud`. |
| [TeleAntiFraud-28k](https://github.com/JimmyMa99/TeleAntiFraud) ([HF, gated](https://huggingface.co/datasets/JimmyMa99/TeleAntiFraud), [paper](https://arxiv.org/abs/2503.24115)) | 28,511 audio+text pairs of telecom fraud calls with reasoning ("slow-thinking") annotations, ACM MM'25 | large (audio) | NOASSERTION, gated | **Chinese**; HF requires access request. Skip tonight. |
| [wspr-ncsu/robocall-audio-dataset](https://github.com/wspr-ncsu/robocall-audio-dataset) | 1,101 **real** robocall recordings (FTC Project Point of No Entry), 16 kHz WAV + transcript column in `metadata.csv` ("order placed for Apple iPhone 11 Pro using your Amazon account... press 1") | ~600 MB repo; metadata.csv is tiny | CC-BY-ND-4.0 | One-sided robocalls, not dialogues. Good for **real phone-channel audio** to stress STT + a few transcript tests. Pull only `metadata.csv` for text. |
| [sumitkant/scam-nonscam-youtube-calls](https://huggingface.co/datasets/sumitkant/scam-nonscam-youtube-calls) | 452 WAV clips of scam / non-scam YouTube calls | 1.3 GB | none tagged | Audio only (no transcripts); useful for end-to-end STT→LLM tests if time allows. Too big on flaky wifi. |
| [AIxBlock/92k-real-world-call-center-scripts-english](https://huggingface.co/datasets/AIxBlock/92k-real-world-call-center-scripts-english) ([paper](https://arxiv.org/abs/2507.02958)) | 91,706 **real** BPO call-center transcripts (inbound/outbound, US/Indian/Filipino English), PII-redacted, word timestamps | big, JSON | CC-BY-NC-4.0 | **Most realistic benign set** (real disfluent call speech). Datasets-server can't parse it; download a few JSON files with `hf download ... --include` and hand-pick ~50 finance calls. |
| [apptek-com/apptek_callcenter_dialogues](https://huggingface.co/datasets/apptek-com/apptek_callcenter_dialogues) | 128.6 h real, multi-accent call-center **audio** (16 domains), split-channel, with a `diarization` config (timestamped speaker segments) | 2,619 rows, large audio | CC-BY-SA-4.0 | Benign audio for testing STT/diarization/prosody FP under accents. Stream a handful of rows. |
| [BothBosu/Scammer-Conversation](https://huggingface.co/datasets/BothBosu/Scammer-Conversation) | 1,000 short generated bank-impersonation chats ("Person A: I'm calling from the bank...") | 0.9 MB | none tagged | Short; extra scam positives. |
| Kaggle "Scam and Non-Scam Call Conversation Dataset" *(page unverified)* | 800 convs, 400/400; used by [hatim00101/bert-scam-classifier](https://huggingface.co/hatim00101/bert-scam-classifier) which reports 100% on 80 test items (a sign the set is too easy) | 800 | CC-BY-NC-ND-4.0 | Needs Kaggle login; skip, BothBosu covers it. |
| [shaw/scambench-training](https://huggingface.co/datasets/shaw/scambench-training) | 37k agent-safety scam scenarios (chat agents being socially engineered), multilingual, with `unsafe_signals` labels | 28 MB | CC-BY-SA-4.0 | Agent-targeted, not phone; skip. |
| KorCCViD / [BaekRok/vishing_data*](https://huggingface.co/datasets/BaekRok/vishing_data_3) | Korean real vishing transcripts | 10k+ | unclear | Korean only. |
| Scam-baiting transcripts ([Wood et al. 2023](https://arxiv.org/abs/2307.01965)) | Real scam-baiter YouTube calls; stage/script analysis | ~hundreds | not released | Paper only, cite for "scams follow scripted stages". |

### How to use them tonight (concrete eval plan)
1. **Positives (scam):** 40 from BothBosu/scam-dialogue test (5 per type) + 40 from multi-agent (mix personalities) + all 20 YouTube real calls.
2. **Benign / false-positive suite:** 40 non-scam from each BothBosu set + **100 banking calls from Lakshan2003 40k** (filter `"bank" in text or "account" in text`) + ~20 hand-picked AIxBlock real transcripts.
3. **Our own held-out "bank ATO" set (the one that matters):** 15-20 scripts we write ourselves for the exact two demo scenarios and their *benign twins* (customer legitimately changes phone number after losing phone; grandparent legitimately wiring to a known grandson for tuition). Write them before 11 PM, never tune the prompt on them.
4. **Streaming metric:** replay each transcript turn-by-turn (as the live system does) and record (a) final verdict, (b) **turn index of first alert**, (c) any alert on benign calls (FP). Report precision, recall, FP-rate on bank-like benign calls, and median "turns-to-alert". ICFD-31k's chunk schema is the template.
5. Normalize all sets to one JSONL: `{id, source, label, scam_type, turns:[{speaker, text}]}`; BothBosu dialogues are single strings, split on `caller:|receiver:|Suspect:|Innocent:`.

```python
from datasets import load_dataset
pos = load_dataset("BothBosu/scam-dialogue", split="test")                 # 320
ma  = load_dataset("BothBosu/multi-agent-scam-conversation", split="test") # 320
yt  = load_dataset("BothBosu/youtube-scam-conversations", split="train")   # 20 real
ben = load_dataset("Lakshan2003/customer_service_client_agent_conversations_40k_multi_task",
                   split="train").shuffle(seed=0).select(range(2000))
ben = ben.filter(lambda r: any(k in " ".join(t["text"] for t in r["conversation"]).lower()
                               for k in ("bank", "account", "transfer", "card")))
```

Caveat for judges: synthetic scam sets are written by LLMs and contain obvious cues ("Officer Johnson from the Social Security Administration"), so near-perfect scores there mean little. Lead with FP rate on bank-like benign calls and with the hand-written held-out set.


## 3. Research: LLM detection of phone scams / social engineering (2023-2026)

### What the literature says (numbers)
| Paper | Finding | Number |
|---|---|---|
| Shen et al. 2024, ["Combating Phone Scams with LLM-based Detection: Where Do We Stand?"](https://arxiv.org/abs/2409.11643) | GPT-4/4o/GLM4 etc. on call transcripts. Main problems named: **biased datasets, low recall, hallucinations** | precision >0.98 on real data, recall ~0.72 *(from search snippet)* |
| Shen et al. CHI'25 LBW, [arXiv 2502.03964](https://arxiv.org/abs/2502.03964) | Per-turn real-time prompting. Binary prompt over-fires on keywords; adding **UNCERTAIN** trades a little recall for much better precision | RT precision 0.70-0.77 → UNC 0.83-0.85 on synthetic keyword-laden calls |
| [PsyScam](https://arxiv.org/abs/2505.15017) (2025), [code+data](https://github.com/KiteFlyKid/PsyScam) | 9 psychological-technique labels on 1,126 BBB / crypto scam reports. Zero-shot LLMs trail fine-tuned encoders on multi-label tactic tagging | RoBERTa F1 0.867; GPT-4.1-mini zero-shot 0.771; Qwen3-30B 0.526. Exact-match accuracy only 0.435 (multi-label is hard) |
| [PreScam](https://arxiv.org/abs/2605.12243) (2026) | 11,573 conversational scams from 178k user reports, structured by a **scam kill chain** with per-turn scammer actions | LLMs capture cues but **struggle to track escalation across turns**; supervised encoders beat zero-shot LLMs at "is this nearing the money stage" |
| ["Anatomy of Conversational Scams"](https://arxiv.org/html/2601.03134) (2026) | LLM-vs-LLM red-teaming. 10 attacker families (AF1 Authority Pressure, AF2 Urgency, AF3 Threat of Loss, AF4 Info Harvesting, AF5 Channel Shift, AF6 Credential Engineering, AF7 Reciprocity, AF8 Sunk-cost, AF9 Rapport, AF10 Payment Engineering), **each with a matching defender move** (verification, delay, de-escalation, data minimization, channel control, payment friction...) | Urgency in 78% of English attacker dialogues |
| ["Talking Like a Phisher"](https://arxiv.org/abs/2507.16291) (2025) | LLM paraphrases of real vishing scripts evade ML vishing classifiers while keeping the meaning | accuracy drop up to **31%** |
| [ConvoSentinel](https://arxiv.org/abs/2406.12263) (EMNLP'24) | Message-level detection + retrieval of similar known SE snippets + conversation-level verdict beats a single LLM pass and is cheaper | n/a |
| [Wood et al. 2023](https://arxiv.org/abs/2307.01965) | Real scam-baiter calls follow **scripted stages**; specific SE techniques cluster in specific stages; emotion is used deliberately | qualitative |
| [RAG real-time fraud](https://arxiv.org/abs/2501.15290) (2025) | Streaming transcript + RAG over policy for private-info requests | 97.98% acc on 100 synthetic calls |

### Prompting approaches that work
1. **Tactic-first, verdict-second (structured output).** Ask the LLM to extract `{tactic, quoted_evidence, turn_id}` items first, then derive the risk level from *which* tactics co-occur. Matches ScamGuardBench's schema and our "quoted evidence" requirement. Reduces hallucinated verdicts: no quote, no flag (validate that the quote is a substring of the transcript, otherwise drop it).
2. **Three-state output (clear / watch / alert)** instead of binary (CHI'25 UNC result).
3. **Stage tracking**: keep a running "scam stage" (pretext → trust → pressure → request → payment) rather than re-judging from scratch; LLMs are weak at escalation tracking (PreScam), so make the state explicit in the prompt or in code.
4. **Context the bank already has beats keywords.** Give the LLM the call's legitimate context ("customer authenticated by KBA; normal call reasons: card lost, address change...") so "wire" or "verify" in a normal call isn't a flag. Main fix for the documented keyword FP.
5. **Rolling summary + last N turns** (summary-memory paper) for flat latency on long calls.
6. **Retrieval of the closest playbook / known-scam example** as the citation (ConvoSentinel, Guardian Angel).
7. **Tactic over keyword robustness:** include paraphrased/keyword-free scam lines in eval (ScamGuardBench `hard`, "Talking Like a Phisher"). An LLM tactic-tagger should be far more robust than keyword rules. That's a robustness claim we can *measure*.

### Failure modes to design around
- **Keyword FPs** in benign calls (payment, ID, fee, verify). In a bank call these words are normal, so this is *our* main risk.
- **Early-vs-late alert trade-off**: early looks like jumping to conclusions; late is useless.
- **Low recall on subtle/real calls** compared with synthetic ones; synthetic data inflates scores.
- **Hallucinated evidence**: enforce verbatim-quote validation.
- **Multi-label confusion**: tactics overlap (authority + fear). Don't make the UI depend on fine-grained tactic accuracy; show tactic chips, fuse at the level of "pressure + payment request + secrecy".
- **Adversarial paraphrase** and **coached victims** (the *customer* says the scammy line, e.g. "I need to send it today, he said not to tell anyone"). Most datasets label the *caller* as the scammer; our vulnerable-customer scenario flips that, so we need our own test scripts.

### Recommended taxonomy for our playbook (map each playbook entry to one of these IDs)
Synthesized from the FTC "4 signs" ([consumer.ftc.gov/articles/0060](https://consumer.ftc.gov/articles/0060-10-things-you-can-do-avoid-fraud), [0120](https://www.consumer.ftc.gov/articles/0120-avoiding-scams-101)), PsyScam's Cialdini-based labels, and the AF1-AF10 families. Small enough (10 tags) for an LLM to tag reliably, and each tag has a **counter-move for the agent**, the way the AF/DF pairing works.

| ID | Tactic | Sources | Example cue in a bank call | Suggested agent counter-move |
|---|---|---|---|---|
| T1 | **Impersonation / authority** | FTC sign 1, PsyScam Authority, AF1/AF6 | "I'm calling on behalf of my mother"; "the IRS/police told me..." | Verify identity via callback to number on file (DF1) |
| T2 | **Urgency / time pressure** | FTC sign 3, PsyScam Urgency, AF2 | "It has to go out in the next hour" | Slow down, offer a hold/cool-off (DF2) |
| T3 | **Fear / threat of loss** | FTC sign 2, PsyScam Fear, AF3 | "or my grandson stays in jail" / "account will be frozen" | De-escalate, explain bank never threatens (DF3) |
| T4 | **Secrecy / isolation** | FTC guidance, Stajano & Wilson | "Please don't tell my daughter"; "they said not to tell the bank" | Name the tactic gently; involve trusted contact (elder protocol) |
| T5 | **Unusual payment method / destination** | FTC sign 4, AF10 | wire to new payee, crypto, gift cards, cash courier, "safe account" | Payment friction / hold; payee verification (DF10) |
| T6 | **Account-control change** (ATO precursor) | bank ATO pattern, AF6 | change phone/email/address, add device, reset 2FA, *then* move money | Step-up auth; never same-call change + transfer |
| T7 | **Verification evasion / info harvesting** | AF4, Substrata-style cue | deflects KBA, "just use the new number", asks *agent* for details | Do not proceed; re-authenticate (DF4/DF6) |
| T8 | **Pretext story** (problem or prize) | FTC sign 2, PsyScam Pretext/Phantom Riches | bail, accident, investment win, tech-support refund, romance | Ask open questions; compare with known scam scripts |
| T9 | **Coaching / third-party control** | our playbook, AF5 channel shift | "he says I need to..."; reading from a script; someone in the background; "stay on the line with them" | Ask to speak with customer alone; callback later |
| T10 | **Identity inconsistency** | FriendZone idea, AF6 | name/relationship/reason changes mid-call; story details contradict profile | Flag mismatch; step-up verification |

Fusion rule of thumb: T5 or T6 **plus** any of T2/T3/T4/T9 = alert; a single T-tag = watch. Mirrors the "no single signal is trusted" principle and the CHI'25 3-state result.

---
## 4. Real-time agent-assist UX patterns (Cresta, Observe.AI, Balto, Verint, Google Agent Assist)

What the vendors do (public material is mostly marketing; no vendor publishes card-level design specs):
- **Cresta** fires hints/checklists only when custom intent models detect a specific moment; supervisors see live alerts + transcript and can whisper-chat the agent ([Behavioral Guidance](https://cresta.com/cresta-behavioral-guidance), [Agent Assist](https://cresta.com/agent-assist)).
- **Observe.AI** "Dynamic Prompts that appear on screen at just the right moment", and a customer quote about not being "bombarded with irrelevant alerts" ([SiliconANGLE](https://siliconangle.com/2023/01/31/observe-ai-debuts-real-time-ai-conversational-prompts-call-center-agents/), [AI Copilots](https://www.observe.ai/ai-copilots)).
- **Balto**: a real-time **checklist** that ticks itself off as the agent says things; moved from phrase-matching to AI triggers, and advises AI triggers only for the trickiest items and prompts that state "exactly what must happen", avoiding "appropriately/properly" ([Smart Checklist webinar](https://www.balto.ai/resources/webinars/meet-the-smart-checklist/)).
- **Verint**: define *only* the situations that warrant intervention; notices go to "a centralized notification window out of the way on the main screen", not a "constant barrage... about sentiment" ([Verint exec brief, PDF](https://verint.com/wp-content/uploads/real-time-coaching-executive-perspective-us.pdf)).
- **Google Agent Assist** ships separate embeddable modules (knowledge, smart reply, summary) in one container panel next to the conversation ([UI modules docs](https://docs.cloud.google.com/gemini-enterprise-cx/agent-assist/ui-modules)).
- **Practitioner write-up** ([OnClarity](https://www.onclarity.com/blog/insight/real-time-agent-assist-guidance-while-the-customer-is-still-on-the-line)): confidence gate ("below threshold it shows nothing"), "precision beats recall", suppress already-dismissed items, cite source + version on every suggestion, visible dismiss + "flag wrong" on every card, warns about **automation bias** (agents read suggestions verbatim) and alert fatigue (clinicians override 73% of medication alerts). Latency budget: cloud STT alone is 500-1,200 ms; beyond ~1 s feels unnatural.

### 5 UI principles for the Baseline dashboard
1. **Silent until it matters; one alert slot.** Default state is a calm green "Verified / Normal" strip. Only *one* primary alert card at a time (highest severity), rendered in a fixed location; lower signals live as small chips in a side rail. No streaming sentiment meters or constant number changes in the agent's eye-line (Verint, OnClarity, Cresta's trigger-only model). The Trust Score moves smoothly (EMA) and never flickers.
2. **Every flag = quote + signal + source.** Card shows the *verbatim line* (highlighted in the transcript, click to jump), which detector(s) agreed (voice-match / synthetic / script / pressure icons), and the playbook citation (e.g. "FTC: unusual payment demand"). No evidence, no card. This is our counter-positioning to Substrata-style opaque scores, and it fights automation bias by letting the agent judge quickly.
3. **Tell the agent what to *do*, in 10 words, with a script line.** Action-first headline ("Do not process the wire. Call back on number on file.") + an optional "say this" line the agent can adapt ("Before we continue, I'm going to call you back on the number we have on file."). Maps each taxonomy tag to its counter-move (section 3). Balto/Cresta checklists suggest a small **"safety checklist"** that ticks off as the agent does it (callback offered, step-up auth done, payment held).
4. **Escalate by agreement, show the agreement.** Yellow = 1 signal ("watching"), red = ≥2 independent signals; the card visibly lists *which* independent baselines disagree with the claimed identity ("Voice ✓ matches enrolled · Audio ✗ synthetic artifacts · Script ✗ ATO pattern"). The demo's money shot: "voice match passes, but two other baselines fail." Three-state also follows the CHI'25 precision result.
5. **Agent stays in control and the UI learns from it.** Dismiss / "not fraud" / "escalate to fraud team" buttons on every card; dismissed tactics stay suppressed for the call; a **timeline strip** under the transcript shows when each signal fired (time-to-alert, the "trigger timeline" from the plan). Never auto-block. Frame pressure as "pressure," never "lying."

Bonus details: keep color for severity only (no decorative red); big readable type (agents glance, they don't read); show latency ("analyzed 0.8 s ago") so stale state is obvious; supervisor view = same cards, list of live calls sorted by risk.

---
## 5. Drop-in open source for tonight

Stars/licenses checked via GitHub API 2026-10-09.

### Streaming STT / VAD / diarization
| Tool | Why | License | Notes |
|---|---|---|---|
| [snakers4/silero-vad](https://github.com/snakers4/silero-vad) (10k stars) | Already in plan; utterance segmentation | MIT | Use `VADIterator` for streaming; AppTek recommends `min_speech 0.25 s` |
| [ufal/whisper_streaming](https://github.com/ufal/whisper_streaming) / [ufal/SimulStreaming](https://github.com/ufal/SimulStreaming) | LocalAgreement policy: emit only words stable across 2 decodes, so live captions don't rewrite themselves | MIT | Copy the *policy* even with mlx-whisper: show partial text grey, committed text black, and run the LLM only on committed text |
| [collabora/WhisperLive](https://github.com/collabora/WhisperLive) (4.3k) | Ready WebSocket Whisper server (faster-whisper backend) | MIT | Fallback if our mlx path is flaky; CUDA-friendly for the 5090 |
| [juanmc2005/diart](https://github.com/juanmc2005/diart) (2k) | **Real-time streaming diarization** (pyannote segmentation + embeddings, 500 ms steps) | MIT | Stretch goal "second voice in background" (coaching cue T9). Needs HF token for pyannote models |
| [pyannote/pyannote-audio](https://github.com/pyannote/pyannote-audio) (10.6k) | Offline diarization / overlap detection | MIT | For building eval data, not live |
| [m-bain/whisperX](https://github.com/m-bain/whisperX) (24k) | Word timestamps + diarization offline | BSD-2 | Turn recorded demo calls into labeled turn-level transcripts fast |
| [resemble-ai/Resemblyzer](https://github.com/resemble-ai/Resemblyzer) | 3-line speaker embedding (GE2E) | Apache-2.0 | Backup if SpeechBrain ECAPA install fights us; ECAPA is more accurate |

### Call-center audio simulation (for the eval set and for robustness)
- **Phone codec in one line:** `ffmpeg -i in.wav -ar 8000 -ac 1 -acodec pcm_mulaw tmp.wav && ffmpeg -i tmp.wav -ar 16000 out.wav` (G.711 mu-law round-trip, which is what Twilio Media Streams deliver).
- [iver56/audiomentations](https://github.com/iver56/audiomentations) (MIT): `AddBackgroundNoise`, `BandPassFilter(300-3400 Hz)`, `Mp3Compression`, `RoomSimulator`. Use for the held-out "noise / phone codec" edge cases in the plan's §4.
- [LCAV/pyroomacoustics](https://github.com/LCAV/pyroomacoustics) (MIT): speaker-into-mic room reverb, which matches the demo channel.
- **Two-voice synthetic calls:** script → ElevenLabs (sponsor credits) with distinct voices for agent/caller → concatenate turns with 300-800 ms gaps → codec round-trip. Use the dataset dialogues from §2 as scripts so audio-level and text-level evals share ground truth.
- Real phone-channel audio for sanity: [wspr-ncsu/robocall-audio-dataset](https://github.com/wspr-ncsu/robocall-audio-dataset) (16 kHz WAV of real robocalls, CC-BY-ND).

### Spoof-detector baselines (for the "start point" on the improvement chart)
Most-downloaded HF audio-deepfake classifiers (unvetted; expect poor transfer to ElevenLabs + phone channel, which is the plan's point): [mo-thecreator/Deepfake-audio-detection](https://huggingface.co/mo-thecreator/Deepfake-audio-detection), [Gustking/wav2vec2-large-xlsr-deepfake-audio-classification](https://huggingface.co/Gustking/wav2vec2-large-xlsr-deepfake-audio-classification), [garystafford/wav2vec2-deepfake-voice-detector](https://huggingface.co/garystafford/wav2vec2-deepfake-voice-detector), [MelodyMachine/Deepfake-audio-detection-V2](https://huggingface.co/MelodyMachine/Deepfake-audio-detection-V2). Also [lab260/Spectra-AASIST3](https://huggingface.co/lab260/AASIST3) (wav2vec2 + AASIST). All plug in via `pipeline("audio-classification", model=...)`.

### Transcript eval harness
| Tool | Use | License |
|---|---|---|
| **Plain Python `eval.py` + JSONL** (recommended) | 60 lines: load normalized JSONL (§2), replay turns, call analyzer, log `{id, label, pred, first_alert_turn, latency_ms, tactics}` + timestamp to `eval_runs.jsonl` for the accuracy-over-time chart. Fastest, no dependencies, fits the judging criterion | n/a |
| [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) (26k) | YAML test cases, side-by-side prompt/model comparison, web viewer. Good if we want a pretty comparison screenshot of prompt v1 vs v3 | MIT |
| [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai) (3k) | Python-native eval with log viewer; OpenAI-compatible providers | MIT |
| [confident-ai/deepeval](https://github.com/confident-ai/deepeval) (19k) | pytest-style LLM tests; has hallucination/faithfulness metrics (could check "quoted evidence is in transcript") | Apache-2.0 |
| scikit-learn `classification_report` / `confusion_matrix` | Metrics | BSD |

Validation trick: assert each `quoted_evidence` is a substring (fuzzy, `rapidfuzz.partial_ratio > 90`) of the transcript, and count hallucinated quotes as a reported metric.

### Frameworks (only if we were starting over; probably don't switch tonight)
[pipecat-ai/pipecat](https://github.com/pipecat-ai/pipecat) (BSD-2, 16k) and [livekit/agents](https://github.com/livekit/agents) (Apache-2.0, 15k) give streaming audio pipelines, Twilio/SIP transports and VAD plugins. Our FastAPI WS skeleton already covers the demo. Pipecat's Twilio serializer is the shortest path if a judge asks "can it take a real phone call?" (stretch).

---

## Steal these 5 ideas
1. **Tactic + verbatim quote + counter-move cards** (ScamGuardBench schema × AF/DF attacker-defender pairing × Phish Eye action card): the LLM outputs `{tactic_id, quote, turn}`; we validate the quote exists; each tactic maps to an agent counter-move and "say this" line. No quote → no flag.
2. **Three-state verdict (clear / watching / alert) escalated only by independent agreement** (CHI'25 UNC result: precision 0.70→0.85). Show the agreement explicitly: "Voice ✓ · Synthetic ✗ · Script ✗".
3. **Time-to-alert as a headline metric + trigger timeline** (ICFD-31k streaming labels): "Baseline flagged at 0:41, 30 s *before* the wire request." Replay transcripts turn-by-turn in eval to measure it.
4. **Benign-twin false-positive suite** (ScamGuardBench `legit_confusable`, CHI'25 keyword-FP finding): for each demo scam, a legit twin (real phone-number change, real wire to a known grandson) plus 100 real banking-style customer-service calls. Lead the results slide with FP rate, not accuracy.
5. **Identity-consistency + coaching checks** (FriendZone's name-consistency rule, our coached-customer cues, diart for a second voice): cheap, explainable signals a voice clone can't fake. Pair them with the bank's context so normal words like "wire" or "verify" don't fire alerts.

## Use these datasets (ranked)
1. **Our own hand-written held-out bank set** (15-20 ATO + grandparent scripts and their benign twins, also rendered to audio via ElevenLabs + codec). The only set that matches the product; never tune on it.
2. **[BothBosu/scam-dialogue](https://huggingface.co/datasets/BothBosu/scam-dialogue)**: 1,600 balanced phone dialogues, 8 types, Apache-2.0, 2 MB, instant. Main positives + basic negatives.
3. **[Lakshan2003 customer-service 40k](https://huggingface.co/datasets/Lakshan2003/customer_service_client_agent_conversations_40k_multi_task)**: filter to ~100-300 banking calls. **The false-positive suite** (verify/account/payment vocabulary, no fraud). 46 MB, instant.
4. **[BothBosu/multi-agent-scam-conversation](https://huggingface.co/datasets/BothBosu/multi-agent-scam-conversation)**: 1,600 longer, personality-varied victims (confused/anxious/trusting ≈ vulnerable-customer scenario), Apache-2.0.
5. **[BothBosu/youtube-scam-conversations](https://huggingface.co/datasets/BothBosu/youtube-scam-conversations)**: 20 *real* scam-baiter calls. Tiny but the only real English dialogue set; report separately as "real-world".
6. **[flowxai/scamguardbench](https://huggingface.co/datasets/flowxai/scamguardbench)** (EN rows of `hard` + `legit_confusable`): keyword-evasion robustness and confusable-legit FP check; copy its schema. Apache-2.0.
7. **[SEConvo](https://zenodo.org/records/12170260)** (CC-BY-4.0): per-message social-engineering labels, to sanity-check turn-level flags.
8. *Stretch:* [ICFD-31k](https://huggingface.co/datasets/rishia2220/icfd-31k) `bank_payment_fraud` streaming chunks (Hinglish) for time-to-detect; [AIxBlock 92k real call-center transcripts](https://huggingface.co/datasets/AIxBlock/92k-real-world-call-center-scripts-english) (CC-BY-NC) for realistic benign speech; [robocall-audio-dataset](https://github.com/wspr-ncsu/robocall-audio-dataset) for real phone-channel audio.
