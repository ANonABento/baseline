# Training the brief-architecture network on another computer (e.g. the RTX 5090)

Notebook: `notebooks/baseline_brief_architecture.ipynb`. Status (2026-10-10): the QUICK path ran end to end on CPU; the FULL path (`QUICK = False`, `FULL_DATA = True`) is **running now on the RTX 5090 machine**. Final results: **pending**.

Live status (2026-10-10): speed check measured **0.145 s/batch** (batch 32), so the full 12 epochs x 8000 rows/dataset (18,000 steps) fit the 90-min budget with **no cuts**; epoch ≈ 220 s. Epoch 1/12: loss 2.653, val 0.405 (mean accuracy over emotion/arousal/delivery on 2000 val rows). Train rows: ami 11,129, diplomacy 9,830, librispeech 3,700, meld 9,570, ravdess 960, synthetic 495; 55,150 segments in total.

Model (two-stage, signals first; `finetuning_plan.md` decision update): Stage A signal model (WavLM-base-plus top 4 + DeBERTa-v3-base top 2 layers fine-tuned, acoustic scalars, modality dropout) trains **only** on emotion, arousal, delivery. Measured per-turn signals (`pitch_st_median`, `pitch_st_spread`, `voiced_frac`, `loudness_db`, `pause_frac`, `speech_rate_wps`, `filler_rate`, `log_words`, `has_audio`) and their deltas vs the speaker's own earlier turns form the primary output `signal_timeline` and feed Stage B, a causal GRU that adds optional, uncalibrated bluff / fabrication / mismatch scores. Labels: this run's synthetic data has only 6 bluff and 12 mismatch labels (30 negotiation turns), so those heads report `insufficient_evidence`; fabrication has 180 synthetic audio labels plus Diplomacy text; more negotiation calls are needed if bluff/mismatch scores are ever wanted.

1. Code: `git clone https://github.com/ANonABento/baseline && cd baseline && git checkout v/voice-model-plan` (or `git pull`).
2. Environment: Python 3.11; PyTorch built for CUDA 12.8+ (the 5090 is Blackwell; older builds fail with "no kernel image"). Used here:
   `uv venv -p 3.11 .venv && uv pip install -p .venv torch torchaudio --index-url https://download.pytorch.org/whl/cu128` (torch 2.11.0+cu128),
   then `uv pip install -p .venv pandas pyarrow transformers librosa soundfile scikit-learn sentencepiece protobuf huggingface_hub tqdm jupyter nbclient ipykernel`
   and `.venv/bin/python -m ipykernel install --user --name baseline-venv` (the notebook's first cell can also install the rest; `peft` only for LoRA).
3. Synthetic ElevenLabs data (gitignored): copy `data/synthetic/<run>/` from the machine that generated it into the same path, or regenerate with
   `python scripts/generate_synthetic_calls.py --calls-per-scenario 6 --emotion-corpus 6` (needs `ELEVENLABS_API_KEY` in `.env`; audio will differ slightly).
   The notebook uses the newest folder in `data/synthetic/` (or `SYNTH_RUN=<path>`). **Check the layout:** a zip made on the Mac extracted one level too deep (`data/synthetic/synthetic/<run>/`) plus a `__MACOSX/` folder; move the run folders up to `data/synthetic/<run>/` and delete `__MACOSX`, or the notebook picks the wrong folder. Run `20261010T113744` has 324 calls.
4. Free the GPU first: `nvidia-smi`; stop other users (here an Ollama model held 19 GB: `ollama ps`, `ollama stop <name>`; it reloads if something calls it).
5. Data (to `data/external/`, about 6 GB now): AMI ihm 10 of 51 shards spread across the corpus (~3 GB; `AMI_MAX_SHARDS = None` for all 15.2 GB), LibriSpeech dev-clean + test-clean
   (**train-clean-100 dropped**: openslr serves ~3 MB/s, so its 6.4 GB cost ~30 min of the time budget), MELD ~1.5 GB (HF), RAVDESS ~0.2 GB (Zenodo, can be slow), Diplomacy small.
   **Download data and models untimed before the timed run** (run the data cells once, or fetch into the same paths/HF cache), so the budget goes to training.
   An interrupted RAVDESS download leaves a partial `data/external/ravdess/Audio_Speech_Actors_01-24.zip` that fails the md5 assert: delete it and rerun.
6. Run all cells with `QUICK = False`, `FULL_DATA = True` (the shipped notebook has `QUICK = True`: change it). **Time budget:** `TIME_BUDGET_MIN = 90` for the whole notebook, measured from the config cell.
   At the start of Stage A the notebook measures s/batch (training), s/row (eval), audio-load and signal-extraction cost, reserves the time needed after Stage A
   (embeddings of every row for Stage B, 3 test passes, shortcut audit, Stage B, save), then keeps `PER_DS_PER_EPOCH = 8000` x `EPOCHS_A = 12` if it fits,
   otherwise drops to 4 (or 2) epochs and shrinks `PER_DS_PER_EPOCH`, and halves `AUDIT_MAX` (30,000, floor 3,000) if the audit would eat the training time; a hard stop ends Stage A at its deadline.
   It prints a `TIME BUDGET:` line and per-200-batch progress with ETA. Epoch selection scores a random `VAL_MAX = 2000` val rows. Sampling still gives each dataset equal weight per epoch; coverage is printed and saved.
7. 5090 / throughput changes: 16-thread audio decode (`N_LOAD_THREADS`) with a 3-deep batch prefetch, thread-safe audio cache and a tokenizer lock; `BATCH = 32` (was 16), `EVAL_BATCH = 96`;
   LR 2.8e-5 (encoders) / 1.4e-3 (heads), sqrt-scaled for the larger batch; 5% warm-up + cosine decay to 10% over the planned steps (speed calibration runs at 10% LR); fused AdamW, TF32, bf16 autocast, non_blocking transfers.
8. Outputs: `data/models/baseline_brief_full.pt`, `results/brief_architecture_full.json` (records datasets, shards, epoch size, coverage, `time_budget` (measured speeds, chosen sizes), batch, LRs, schedule, `stage_a_tasks`, `stage_b_inputs`, audit rows, val rows, total wall minutes). Copy both back.
