# Training the brief-architecture network on another computer (e.g. the RTX 5090)

Notebook: `notebooks/baseline_brief_architecture.ipynb`. Status: the QUICK path ran end to end on CPU; the FULL path (`QUICK = False`, `FULL_DATA = True`) has NOT been run yet.

1. Code: `git clone https://github.com/ANonABento/baseline && cd baseline && git checkout v/voice-model-plan` (or `git pull`).
2. Environment: Python 3.11; PyTorch built for CUDA 12.8+ (the 5090 is Blackwell; older builds fail with "no kernel image"),
   e.g. `pip install torch --index-url https://download.pytorch.org/whl/cu128`. The notebook's first cell installs the rest
   (pandas, pyarrow, transformers, librosa, soundfile, scikit-learn, sentencepiece, protobuf, huggingface_hub; `peft` only for LoRA).
3. Synthetic ElevenLabs data (gitignored): copy `data/synthetic/<run>/` from the machine that generated it into the same path, or regenerate with
   `python scripts/generate_synthetic_calls.py --calls-per-scenario 6 --emotion-corpus 6` (needs `ELEVENLABS_API_KEY` in `.env`; audio will differ slightly).
   The notebook uses the newest folder in `data/synthetic/` (or `SYNTH_RUN=<path>`).
4. Disk: about 60 GB free. Downloads on first run (to `data/external/`): AMI ihm all 51 shards 15.2 GB parquet (+ extracted wavs),
   LibriSpeech train-clean-100 6.4 GB + dev/test-clean, MELD ~1.1 GB train + dev/test, RAVDESS ~0.2 GB, Diplomacy small.
5. Run all cells with `QUICK = False`, `FULL_DATA = True` (defaults in the config cell; the shipped notebook has `QUICK = True`: change it).
   Every dataset is loaded in full. Sampling gives each dataset equal weight: each epoch draws `PER_DS_PER_EPOCH = 8000` rows from each of the 6 datasets
   (48k rows/epoch, 12 epochs). Datasets bigger than 8000 are walked through a shuffled order that continues across epochs, so every row is used before any repeats
   (AMI ~94k train rows is covered once in 12 epochs; LibriSpeech ~2.6x; small sets like RAVDESS recycle). The notebook prints the coverage (fraction of each dataset's
   train rows used) and saves it in the results JSON. Audio cache is limited to `CACHE_GB = 8`. Time per epoch on the 5090 is UNMEASURED: check epoch 1 and
   change `PER_DS_PER_EPOCH` / `EPOCHS_A` if it is too slow.
6. Outputs: `data/models/baseline_brief_full.pt`, `results/brief_architecture_full.json` (records datasets, shards, epoch size). Copy both back.
