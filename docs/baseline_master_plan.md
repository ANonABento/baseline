# Baseline: Hackathon Master Plan & Execution Blueprint

> *"To detect what's real and fake - we must define a baseline."*

---

## 1. Project Overview & Core Thesis
* **Project Name:** Baseline
* **Mission:** Protecting vulnerable populations (low-income families, seniors) from high-pressure financial scams, predatory telemarketers, and real-time AI deepfake voice/video impersonations.
* **Why the Name Fits:** In an era of synthetic media and manipulation, **Baseline** represents the ground truth. By continuously measuring acoustic biometrics and dialogue against verified human baselines, the system flags anomalies, deepfakes, and false claims in real-time.
* **Hardware Advantage:** Powered locally by an **RTX 5090**, enabling high-speed offline audio processing, stress/emotion analysis, and deepfake detection without cloud latency.

---

## 2. Core Technical Architecture
1. **Audio Ingestion & Streaming:** Captures call audio feeds (microphone or system audio).
2. **Parallel Inference Engine (RTX 5090):**
   * **Stream A (Content & Intent):** Whisper-Large-v3 for low-latency streaming STT, paired with a local LLM (Llama 3 via Ollama) and a RAG vector DB (Chroma/FAISS) loaded with known scam patterns and financial truths.
   * **Stream B (Security & Biometrics):** Acoustic feature extractors (`wav2vec2`) for stress/pitch spike detection + ASVspoof/RawNet2 classifiers to detect voice-changer artifacts and synthetic audio generation.
3. **Real-Time Dashboard UI:** Displays a live transcript, Trust Score, Stress Meter, and flashing alert cards for deepfakes and scam triggers.

---

## 3. Sponsor Tools & Integration Strategy

### 1. Replit | App Development
* **What you get:** Two days of unlimited usage.
* **Usage:** Hosting and rapid iteration of the frontend web application client dashboard.
* **Promo Code:** `FUTUREOFWORKREPLIT`

### 2. Nebius Token Factory | AI Model API Credits
* **What you get:** $100 in Token Factory credits per participant.
* **Usage:** Powering high-speed cloud LLM fallback or embeddings for the RAG fact-checking backend.
* **Redemption:** Scan the QR code / complete form, top up in profile using your unique code.

### 3. ElevenLabs | AI Voice & Audio
* **What you get:** One free month of Creator tier (131k credits).
* **Usage:** **Crucial for testing!** Generate synthetic deepfake test voice clips to prove your deepfake detection module catches voice changers during the live demo.
* **Redemption:** Join ElevenLabs Discord $\rightarrow$ `#coupon-codes` $\rightarrow$ Start Redemption $\rightarrow$ SF Tech Week Hackathon at Stanford.

### 4. Maritime | Persistent AI Agent Hosting
* **What you get:** 3 free months of Scale plan ($500/mo value). Supports up to 500 agents (60 awake at once) with persistent state and public URLs.
* **Usage:** Hosting background monitoring agents or webhook handlers.
* **Promo Code:** `STANFORDFARM` (Add promotion code at checkout on maritime.sh).

### 5. World Labs | 3D World Creation & API Access
* **What you get:** 1-month free trial of Marble + API credits.
* **Usage:** Optional environment rendering if expanding to immersive UI elements.
* **Codes:** `SUBSCRIPTION-1-MONTH` (Marble) | `30K-CREDITS-BUILD` (API at platform.worldlabs.ai).

### 6. SharedNet | Multi-Agent Coding Collaboration
* **What you get:** A shared workspace where team coding agents (Claude Code, Cursor, Gemini CLI) exchange updates, coordinate work, and leave handoffs.
* **Usage:** Syncs your coding agents so they don't overwrite each other's code.
* **Get Started:** One teammate signs in at `sharednet.ai`, creates a Room, shares the invite command with teammates' coding agents.

---

## 4. Sprint Task Board

### Sprint 1: Setup & Infrastructure
- [ ] Initialize Replit project and connect SharedNet room for coding agents (`sharednet.ai`).
- [ ] Redeem Nebius Token Factory credits and configure API keys.
- [ ] Set up local RTX 5090 environment with PyTorch & Whisper-Large-v3.
- [ ] Configure ElevenLabs account to generate test deepfake voice samples for demo validation.

### Sprint 2: Audio Stream & Deepfake Detector
- [ ] Build real-time microphone / audio stream capture in frontend.
- [ ] Implement streaming STT with Whisper for live transcription.
- [ ] Integrate RawNet2 or ASVspoof classifier for voice-changer anomaly detection.
- [ ] Build acoustic stress / pitch spike analyzer model.

### Sprint 3: RAG & Fact-Checking Engine
- [ ] Compile scam pattern database & predatory financial scripts dataset.
- [ ] Setup Chroma/FAISS vector store with Nebius LLM embeddings.
- [ ] Build real-time semantic matcher to flag false claims and high-pressure threats.

### Sprint 4: Real-Time UI Dashboard & Alerts
- [ ] Design dark-mode cyber security dashboard in Tailwind CSS.
- [ ] Implement Live Trust Score & Stress Meter widgets.
- [ ] Add flashing warning cards for Deepfake & Scam detection triggers.

### Sprint 5: Demo Polish & Pitch Script
- [ ] Record live test run with an ElevenLabs deepfake audio sample.
- [ ] Refine 3-minute pitch narrative ("To define a baseline...").
- [ ] Deploy agent instance on Maritime (`STANFORDFARM`).