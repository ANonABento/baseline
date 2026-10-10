# Data and model licences (V)

Scope decision (Dae, 2026-10-10): **hackathon use only, research.** Nothing below is cleared for a commercial product. Licence text was read through a summarising fetch tool or an API tag, not by a lawyer; **a human must read the originals before any commercial use**. Not legal advice.

| Item | Licence (as read) | Used for | Shippable in a product? | Status |
|---|---|---|---|---|
| LibriSpeech (test-clean already, dev/train subsets later) | CC BY 4.0 (OpenSLR; attribution) | read-speech class, real class for spoof eval | yes with attribution (UNVERIFIED by lawyer) | in use |
| AMI headset mix, HF `edinburghcstr/ami` | CC-BY-4.0 (HF tag, not gated) | spontaneous-speech class, per-speaker history | yes with attribution (UNVERIFIED) | 3 shards downloaded (`data/external/ami/`) |
| RAVDESS speech, Zenodo 1188976 | CC BY-NC-SA 4.0 (Zenodo API `cc-by-nc-sa-4.0`) | acted-emotion prototype (S1) | **NO: non-commercial.** Weights trained on it must not ship | downloaded, md5 verified |
| CREMA-D | ODbL (share-alike), official access path unclear; HF mirror is unofficial with no licence text | acted-emotion prototype | **NO until a lawyer reads share-alike scope** | not downloaded |
| MSP-Podcast, IEMOCAP, SUSAS, BESST, ESD, Switchboard | signed agreement and/or fee | none | n/a | not available |
| `microsoft/wavlm-base-plus` | licence file linked, text not read | audio encoder A | UNVERIFIED | human to read LICENSE |
| `emotion2vec/emotion2vec_plus_large` | HF `model-license` (FunASR); GitHub shows MIT badge: sources disagree | audio encoder B | UNVERIFIED | human sign-off |
| `audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim` | CC BY-NC-SA 4.0 | research comparison only | **NO** | not downloaded |
| Whisper large-v3-turbo, DeBERTa-v3-base | MIT (model cards) | ASR, text encoder | yes (UNVERIFIED by lawyer) | in use / planned |

Rules for this repo:
- Weights or numbers derived from a **NO** row are labelled "research-only, not shippable" wherever they appear (README, results, slides).
- Datasets stay under `data/external/` (gitignored); only scripts, manifests (hashes, licence tags) and aggregate results are committed.
- No participant recordings exist; none are made.
- Sources and access checks: `docs/research/open_datasets.md`, `docs/research/voice_signal_evidence.md`.
