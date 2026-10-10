# Spoof Detection Research (Baseline hackathon)

_Written 2026-10-09. Scope: detecting ElevenLabs-quality voice clones in call audio, locally on M5 MacBook (24 GB, MPS/MLX), ~6 h ML time. Companion to master plan §3 and §10._

> Status: complete. Jump to **Do this tonight** at the bottom.

## TL;DR

1. **Open-source detectors trained on academic data fail on modern commercial TTS.** Even the best post-trained SSL models hit ~25-34% EER on Deepfake-Eval-2024 (real social-media deepfakes, incl. commercial TTS), while scoring 1-5% on In-the-Wild. Vendor benchmarks put old open-source models (RawNet2/AASIST/LCNN/Wav2Vec2) at ~48-63% accuracy on 25 modern TTS systems including ElevenLabs. **Training on our own ElevenLabs clones is the right call; a pretrained checkpoint is a baseline/feature source, not the answer.**
2. **Frozen SSL + logistic regression is a published, competitive recipe** (Pascu et al., Interspeech 2024: <2k trainable params, In-the-Wild EER 30% -> ~8%). **Use middle layers, not the last layer.** WavLM-Base is markedly weaker OOD than WavLM-Large / XLS-R-300M (In-the-Wild EER ~18% vs ~6%), so extract features from **both** wavlm-base-plus and one large model and let the held-out-speaker eval decide.
3. **Biggest demo risks are shortcut learning** (silence, loudness, sample rate/codec, mic channel, speaker identity). A clone recorded through the same speaker->mic path as real voices, plus loudness/silence normalization, is worth more than any model swap.

---

## 1. What works for modern commercial TTS / voice clones (2024-2026)

### 1.1 ASVspoof 5 (2024 challenge, overview published Jan 2026)
- 53 teams. Data is crowdsourced (MLS-based, many recording conditions), with ~32 attack algorithms incl. newer TTS/VC, **adversarial attacks**, and **neural codec / compression** conditions. Organizers' headline: many systems perform well, but **performance degrades under adversarial attacks and neural encoding/compression**. [overview arXiv 2601.03944](https://arxiv.org/html/2601.03944v1), [database paper 2408.08739](https://arxiv.org/pdf/2408.08739)
- **Closed condition** (no pretrained SSL allowed): best Track-1 EER ~8.6%. **Open condition** (SSL allowed): top systems ~5% EER / minDCF ~0.15-0.17, e.g. Reality Defender 5.56% EER ([2410.07379](https://arxiv.org/pdf/2410.07379)), Vicomtech-UGR ensemble 5.02% vs 28.41% closed ([2408.10361](https://deepfake-demo.aisec.fraunhofer.de/related_work/2408.10361)). **Takeaway: the SSL front-end is the single biggest win** (roughly 5x lower EER than training from scratch).
- ASVspoof 5 contains **no ElevenLabs** audio; its attacks are open-source systems.

### 1.2 In-the-Wild (ITW) and real-world benchmarks
- **In-the-Wild** (Müller et al., Interspeech 2022, "Does audio deepfake detection generalize?"): 37.9 h of real + fake audio of 58 politicians/celebrities scraped from the web. Models trained on ASVspoof 2019 that scored ~1% in-domain dropped to **30-90% EER** on ITW. It became the standard OOD test. [arXiv 2203.16263](https://arxiv.org/abs/2203.16263)
- **Speech DF Arena** (Idiap, IEEE OJSP 2026), 14 eval sets, all models trained on ASVspoof 2019 ([arXiv 2509.02859](https://arxiv.org/html/2509.02859v1), [leaderboard](https://huggingface.co/spaces/Speech-Arena-2025/Speech-DF-Arena)):

  | Model (GitHub) | Params | ITW EER | Avg EER (14 sets) | CodecFake | SONAR |
  |---|---|---|---|---|---|
  | XLSR+SLS (QiShanZhang/SLSforASVspoof-2021-DF) | 340M | 7.45 | **13.84** | 33.4 | 24.7 |
  | XLSR-Mamba (swagshaw/XLSR-Mamba) | 319M | **6.70** | 14.21 | 35.3 | 24.3 |
  | Wav2Vec2-AASIST (TakHemlata/SSL_Anti-spoofing) | 318M | 11.19 | 18.02 | 43.4 | 46.1 |
  | WavLM-ECAPA | 102M | 34.64 | 28.74 | 46.2 | 41.9 |
  | AASIST (no SSL) | 0.3M | 43.00 | 34.49 | 51.1 | 57.5 |
  | RawNet2 (no SSL) | 17.6M | 49.00 | 35.75 | 49.8 | 40.4 |

  Findings: **no model wins everywhere**; all collapse on **CodecFake** (neural-codec TTS, i.e. the architecture family of modern commercial TTS) at 33-51% EER; SONAR (newer TTS) 24-58%. Non-SSL models are near chance OOD.
- **Deepfake-Eval-2024** (real deepfakes from social media, 2024): open-source detectors lose **~48-50% AUC** vs. academic benchmarks; commercial detectors do better. [arXiv 2503.02857](https://arxiv.org/pdf/2503.02857v3). Even NII's AntiDeepfake models (post-trained on 74k h) sit at **26-34% EER zero-shot** on it.
- **Vendor benchmarks (treat as biased):** Podonos tested ~25 modern TTS incl. ElevenLabs, 4,524 clips, six formats: commercial detectors 96-98%, open-source Wav2Vec2/RawNet2/LCNN/AASIST **~48-63% accuracy** (near chance). [Resemble summary](https://resemble.ai/resources/audio-deepfake-detection-benchmark-results-how-8-systems-performed-in-2026), [Podonos](https://www.podonos.com/blog/deepfake-audio-benchmark).

### 1.3 SSL-feature approaches
- **Frozen SSL + linear/LR** (Pascu et al., Interspeech 2024): frozen wav2vec2 variants + logistic regression, <2k trainable params; avg EER over 8 datasets 30.9% (RawNet2) -> **8.8%**; ITW ~30% -> ~8%. Larger backbone + **weaker regularization** worked best; well calibrated; **prediction entropy is a good "abstain" signal**. [arXiv 2309.05384](https://arxiv.org/abs/2309.05384), [ISCA](https://www.isca-archive.org/interspeech_2024/pascu24_interspeech.html). Follow-up (2026): a truncated SSL backbone + logistic classifier running in a browser plugin beat AASIST by ~10% and ran ~40% faster ([arXiv 2606.30780](https://arxiv.org/abs/2606.30780), [code](https://github.com/OctavianPascu97/Audio-Deepfakes-Browser-Plugin)). **This is basically our plan, so it is defensible to judges.**
- **Fine-tuned SSL + AASIST/SLS/Mamba back-ends** (XLS-R-300M based): best ASVspoof-trained OOD numbers (ITW 6.7-11%), but they need GPU fine-tuning (hours) and RawBoost aug. Not feasible to retrain tonight; their released checkpoints are usable for inference only (see §2).
- **Large-scale post-training (NII AntiDeepfake, 2025):** SSL backbones post-trained on 56k h real + 18k h fake (incl. MLAAD, ASVspoof5, CodecFake) across 100+ languages. Zero-shot ITW EER **1.2-4.7%**, but Deepfake-Eval-2024 still 26-34%. [arXiv 2506.21090](https://arxiv.org/html/2506.21090v4)
- **Layer choice matters:** lower/middle layers carry the spoofing cues; output layer is worst (details §3).

### 1.4 Known generalization failures
| Failure | Evidence | Implication for us |
|---|---|---|
| Unseen generators | ITW: 30-90% EER for ASVspoof-trained models; CodecFake 33-51% for all Arena models | Train on ElevenLabs directly; also test a non-ElevenLabs TTS (macOS `say`, Piper/Kokoro) as a "never seen" edge case |
| Neural codecs / compression (MP3, Opus, phone codecs) | ASVspoof 5 overview: degradation under neural encoding/compression | Augment both classes with the same codecs, never only one class |
| Replay (speaker->mic) | Müller et al., Interspeech 2025 ([arXiv 2505.14862](https://arxiv.org/abs/2505.14862), [ReplayDF](https://deepfake-demo.aisec.fraunhofer.de/replay_df)): 109 speaker-mic combos; best model W2V2-AASIST EER 4.7% -> **18.2%** after replay; RIR-augmented retraining only recovers to 11.0%. Errors are mostly **fakes passing as real** | Record both real and fake through the exact demo speaker->mic path |
| Noise / reverb | AntiDeepfake authors note RawBoost alone is "insufficient" for real-world audio and recommend MUSAN noise/music aug | Add noise + RIR aug to both classes |
| Speaker/language shift | Arena: no single model wins across datasets | Holdout-speaker eval is mandatory |

---

## 2. Pretrained checkpoints: which are credible for ElevenLabs-style audio?

Evidence is ranked by independent, out-of-domain evaluation (In-the-Wild, multi-dataset arenas), not downloads. **None of these has a published, independent ElevenLabs-specific EER.** Treat every one as "unproven on ElevenLabs" until it passes our own eval set.

| Checkpoint | Backbone / size | Training data | Independent OOD evidence | License | Mac CPU/MPS? | Verdict |
|---|---|---|---|---|---|---|
| **`Speech-Arena-2025/DF_Arena_500M_V_1`** ([card](https://huggingface.co/Speech-Arena-2025/DF_Arena_500M_V_1)) | SSL ~500M + conformer, `pytorch_model.bin` | ASVspoof19/24, **CodecFake**, LibriSeVoc, DFADD, CtrSVDD, SpoofCeleb, **MLAAD**, EnvSDD | Own card: avg EER 5.78% over 14 sets, ITW 1.76%, CodecFake 6.36%, SONAR 1.90%. Arena mirror: mean 5.09% over 24 sets ([mirror](https://huggingface.co/SpeechAntiSpoofingBenchmarks/DF_Arena_500M_V_1)). From the Idiap/TalTech Arena team ([RAPTOR arXiv 2603.06164](https://arxiv.org/abs/2603.06164)) | **Non-commercial** (custom) | Likely; transformers `pipeline("antispoofing", trust_remote_code=True)`, set `device="mps"` or cpu. Remote code **untested on transformers 5.19**: budget 20 min | **Best zero-shot candidate.** Only one trained on codec-TTS + MLAAD and published OOD numbers |
| **NII AntiDeepfake** `nii-yamagishilab/wav2vec-small-anti-deepfake` (95M) / `wav2vec-large-anti-deepfake(-nda)` (317M), also MMS-300M, XLS-R-1B/2B ([paper](https://arxiv.org/abs/2506.21090), [code](https://github.com/nii-yamagishilab/AntiDeepfake)) | wav2vec2 base/large, mean-pool + linear | 56k h real + 18k h fake, 100+ languages (incl. MLAAD, ASVspoof5, CodecFake) | Paper zero-shot ITW: Small 4.2%, Large 1.9-2.3%, XLS-R-1B 1.35%. **Deepfake-Eval-2024: 26-34%** (honest real-world number). Arena: Small ITW 5.31% | CC BY-NC-SA 4.0 (weights), BSD-3 code | Official loader needs **fairseq 0.12.2** (painful on Py3.11/arm64). **Shortcut:** ONNX export at [`SpeechAntiSpoofingBenchmarks/Wav2Vec2-Small-AntiDeepfake`](https://huggingface.co/SpeechAntiSpoofingBenchmarks/Wav2Vec2-Small-AntiDeepfake) (`wav2vec2-small-antideepfake.onnx`, 378 MB, input `wav` [B,T] 16 kHz, output `logits`; Large also mirrored) via `onnxruntime` CPU | Strong second candidate; also a **better frozen feature extractor** than vanilla WavLM (already tuned for spoof cues) |
| `garystafford/wav2vec2-deepfake-voice-detector` ([card](https://huggingface.co/garystafford/wav2vec2-deepfake-voice-detector)) | XLS-R-300M (via Gustking), 1.26 GB | 1,866 clips: YouTube real vs 6 TTS **incl. 173 ElevenLabs** | Only a 187-clip **random split** (97.9% acc). No speaker holdout, no external test. Real = 14 YouTube videos, so channel shortcut is likely | Apache-2.0 | Yes, standard `AutoModelForAudioClassification` | Worth a 10-min eval because it *saw* ElevenLabs; do not trust its card numbers |
| `Gustking/wav2vec2-large-xlsr-deepfake-audio-classification` | XLS-R-300M, 1.26 GB | Undocumented (card is 544 bytes) | None | Apache-2.0 | Yes | Skip |
| **`mo-thecreator/Deepfake-audio-detection`** (our candidate 1) ([card](https://huggingface.co/mo-thecreator/Deepfake-audio-detection)) | wav2vec2-base, 95M, 378 MB | **Undocumented** ("fine-tuned on the None dataset"); 98.8% acc on its own unnamed split, May 2024 | **None.** Not in any arena. Popular (23k dl/mo) only because it's an easy `pipeline()` | Apache-2.0 | Yes (already working on MPS, 60-250 ms) | Fine as the *"before"* point on the improvement chart; expect it to miss ElevenLabs. Its V2 fork `MelodyMachine/Deepfake-audio-detection-V2` has the same problem |
| XLSR+SLS / XLSR-Mamba / W2V2-AASIST (GitHub, ASVspoof19-trained) | XLS-R-300M + back-end, ~320M | ASVspoof 2019 LA only | Arena ITW 6.7-11.2%, **CodecFake 33-43%, SONAR 24-46%** | MIT (SLS) | Need fairseq; ONNX at [`SpeechAntiSpoofingBenchmarks/XLSR-SLS`](https://huggingface.co/SpeechAntiSpoofingBenchmarks/XLSR-SLS) | Superseded by DF_Arena / AntiDeepfake (trained on far more data) |
| `MattyB95/AST-ASVspoof5-*` | AST | ASVspoof5 | We measured: calls real speech spoof | - | - | Dead (already ruled out in §10) |

**Our candidate 2: `microsoft/wavlm-base-plus` frozen + LR.** WavLM-Base is the *weakest* of the mainstream SSL backbones for OOD spoof detection: ITW EER 17.8% (best layer 4) vs 6.0% WavLM-Large (layer 8) and 5.6% XLS-R-300M (layer 6) when trained on ASVspoof5 ([Serrano et al. 2025, arXiv 2509.12003](https://arxiv.org/html/2509.12003v1)). Arena: WavLM-ECAPA 34.6% ITW. It is fine *in-domain* (we train on ElevenLabs directly, and it's fast: 40 ms / 3 s on MPS), but **add one stronger frozen backbone** and compare on the holdout speaker:
- `microsoft/wavlm-large` (316M, MIT) or `facebook/wav2vec2-xls-r-300m` (Apache-2.0): ~3x WavLM-base compute, so roughly 100-150 ms per 3 s window on MPS (estimate). Still real-time at 1 window/sec.
- Or the AntiDeepfake Small backbone (95M, same cost as WavLM-base, already spoof-tuned; NC license).

**Recommendation:** keep mo-thecreator as the "before" number. Run **DF_Arena_500M** zero-shot as the "best off-the-shelf" number (second chart point, and a candidate fusion input). Ship **our LR on frozen features**, with the backbone picked by holdout-speaker EER. If DF_Arena is good on our ElevenLabs eval, fuse its score with our LR (average of logits, or a 2-feature LR) for the demo.

> Licensing note for the pitch: DF_Arena and AntiDeepfake weights are **non-commercial**. Fine for a hackathon demo; say so if judges ask about the bank product. WavLM (MIT), XLS-R (Apache-2.0) and our LR are commercially clean.

---

## 4. Datasets we can pull a small slice of tonight (<1 GB)

| Dataset | What | Size / access | License | ElevenLabs? | How to get a slice |
|---|---|---|---|---|---|
| **garystafford/deepfake-audio-detection** ([HF](https://huggingface.co/datasets/garystafford/deepfake-audio-detection)) | 1,866 clips, 16 kHz mono FLAC, 2.5-13 s. Fake: ElevenLabs 173 (`el_`), Polly 209, Speechify 211, Luvvoice 156, Hume 116, Kokoro 68. Real: 14 YouTube videos | ~1.6 GB repo total; **ElevenLabs folder ~tens of MB**. Not gated | CC BY 4.0 | **Yes, 173 clips** | `hf download garystafford/deepfake-audio-detection --repo-type dataset --include "fake/el_*" --local-dir data/ext/gary` (also `fake/hu_*`, `fake/sp_*` as extra "unseen commercial TTS" test). **Don't use its real/ folder as training reals** (14 YouTube sources, channel shortcut) |
| **Mendeley "Fake Audio Dataset (ElevenLabs & Respeecher)"** ([page](https://data.mendeley.com/datasets/79g59sp69z/1)) | 600 WAV, 22.05 kHz, 8-10 s: ElevenLabs 335 (282 voice-to-voice, 53 TTS), Respeecher 265 | ~250 MB est. One "Download All" zip, no login | CC BY 4.0 | **Yes, 335 clips incl. speech-to-speech** | Browser download. Fakes only. **Resample to 16 kHz** (22.05 kHz is an instant shortcut otherwise) |
| **In-the-Wild** ([HF](https://huggingface.co/datasets/mueller91/In-The-Wild), [site](https://deepfake-total.com/in_the_wild)) | 31,779 clips, 58 public figures, 20.8 h real / 17.2 h fake (web-sourced, mixed generators, 2021-22 era) | Single **8.2 GB zip**, not gated. Avg ~0.3 MB/clip | Apache-2.0 per site; HF tag says CC BY-SA 4.0 | Unknown generators | **Range-request slice** (tested tonight, works): script below pulls N random clips per class, ~100 MB for 150+150. Use as an **OOD sanity test**, not training |
| **MLAAD** ([HF](https://huggingface.co/datasets/mueller91/MLAAD)) | TTS fakes, 38 languages, ~100 open-source TTS models (XTTS, VITS, Bark, etc.), `fake/<lang>/<model>/` + `meta.csv`; reals = M-AILABS | 183 GB total; **gated (auto-accept)**, `hf auth login` | CC BY-NC 4.0 | No (open-source TTS only) | `hf download mueller91/MLAAD --repo-type dataset --include "fake/en/<model>/*"` for 2-3 English model folders. Use as "unseen generator" test fakes |
| **behavioralsignals/deepfake-detection-demo** ([HF](https://huggingface.co/datasets/behavioralsignals/deepfake-detection-demo)) | 22 utterances, 11 languages; fakes cloned with **ElevenLabs** (6) and Speechify (5) from Common Voice prompts | 6.7 MB, not gated | unspecified (treat as eval only) | **Yes (6)** | `hf download behavioralsignals/deepfake-detection-demo --repo-type dataset`. Good tiny **external** smoke test: cloned speaker vs. its own real reference |
| ASVspoof 2019 LA ([DataShare](https://datashare.ed.ac.uk/handle/10283/3336)) | 2018-era TTS/VC, VCTK speakers | LA.zip ~7 GB | ODC-By | No | **Skip.** Old generators; Podonos and the ITW paper both show it doesn't transfer |
| ASVspoof 5 ([Zenodo 14498691](https://zenodo.org/records/14498691)) | 2024 crowdsourced, codecs, adversarial | 142 GB in 6.6 GB tar shards | ODC-By (check LICENSE.txt) | No | **Skip tonight.** Smallest unit is a 6.6 GB shard |
| WaveFake ([Zenodo](https://zenodo.org/record/5642694)) | Vocoder-only fakes of LJSpeech/JSUT | 16 GB+ zip | CC BY-SA 4.0 | No | **Skip.** Single speaker, vocoder-only, irrelevant to ElevenLabs |
| ReplayDF ([page](https://deepfake-demo.aisec.fraunhofer.de/replay_df)) | MLAAD/M-AILABS re-recorded through 109 speaker-mic pairs | Request-based | Non-commercial research | No | Skip; record our own replay instead (faster, matches our room) |

**Real-speech side** (needed to balance external fakes, else "external data = fake" becomes the shortcut): LibriSpeech `test-clean` (346 MB, CC BY 4.0, [openslr.org/12](https://www.openslr.org/12)) and the ITW bona-fide slice. Prefer reals that went through the **same pipeline** as the fakes (same resample, same loudness norm, same augmentation).

### In-the-Wild slice script (tested 2026-10-09, stdlib only)
```python
# usage: python -I itw_slice.py <out_dir> <n_per_class>   (150 -> ~100 MB)
import io, sys, zipfile, random, urllib.request, csv, os
URL = "https://huggingface.co/datasets/mueller91/In-The-Wild/resolve/main/release_in_the_wild.zip"
class HttpFile(io.RawIOBase):
    def __init__(s, url):
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-0"}))
        s.url = r.geturl(); s.size = int(r.headers["Content-Range"].split("/")[1]); s.pos = 0
        s.cs, s.cb = -1, b""
    def seekable(s): return True
    def readable(s): return True
    def tell(s): return s.pos
    def seek(s, off, wh=0):
        s.pos = off if wh == 0 else s.pos + off if wh == 1 else s.size + off; return s.pos
    def read(s, n=-1):
        if n < 0: n = s.size - s.pos
        n = min(n, s.size - s.pos)
        if n == 0: return b""
        if not (s.cs <= s.pos and s.pos + n <= s.cs + len(s.cb)):
            end = min(s.size, s.pos + max(n, 256 << 10)) - 1
            r = urllib.request.Request(s.url, headers={"Range": f"bytes={s.pos}-{end}"})
            s.cs, s.cb = s.pos, urllib.request.urlopen(r).read()
        b = s.cb[s.pos - s.cs: s.pos - s.cs + n]; s.pos += len(b); return b
out, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 150
z = zipfile.ZipFile(HttpFile(URL)); names = z.namelist()
meta = [x for x in names if x.endswith("meta.csv")][0]; prefix = meta.rsplit("meta.csv", 1)[0]
rows = list(csv.DictReader(io.TextIOWrapper(z.open(meta))))   # cols: file, speaker, label (bona-fide|spoof)
random.seed(0); os.makedirs(out, exist_ok=True); picked = []
for lab in ("bona-fide", "spoof"):
    picked += random.sample([r for r in rows if r["label"] == lab], n)
with open(os.path.join(out, "labels.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader()
    for r in picked:
        open(os.path.join(out, r["file"]), "wb").write(z.read(prefix + r["file"])); w.writerow(r)
```
If wifi drops mid-run, just rerun (seeded, overwrites). For eval, sample by **speaker** so no ITW speaker appears in two splits.

---

## 3. Is frozen SSL + logistic regression sound for a few hundred clips?

**Yes.** It is the published recipe of Pascu et al. (Interspeech 2024; <2k trainable params, best OOD generalization among their variants, well calibrated) and the 2026 browser-plugin follow-up. With a few hundred clips, a fine-tuned network would overfit to speakers/channel; a linear probe on frozen features can't memorize much. Caveat: the probe will only be as general as the *diversity of our fakes and channels*, not the number of clips.

### 3.1 Which layers
- **Not the last layer.** Lower/middle layers carry spoof artifacts; upper layers carry content/speaker info and generalize worse. El Kheir et al. (NAACL Findings 2025, [arXiv 2502.03559](https://arxiv.org/abs/2502.03559)): the first **4-6 layers (base)** / **10-12 (large)** already give near-full performance. Serrano et al. 2025 ([arXiv 2509.12003](https://arxiv.org/html/2509.12003v1)): best single layer WavLM-Base **4**, wav2vec2-Base **8**, WavLM-Large **8**, XLS-R-300M **6**; "connecting a classification head directly to the output layer is detrimental."
- **Recipe for wavlm-base-plus (13 hidden states incl. CNN output):** run once with `output_hidden_states=True`, cache **all layers** to disk (`[n_windows, 13, 768]` mean-pooled, plus std-pooled if cheap). Then sweep on speaker-grouped CV in seconds:
  1. single layers 2..8,
  2. **average of layers 3-6** (quick, robust default),
  3. concat mean-pool of layers 3-6 (3072-d, use stronger L2).
  Pick by holdout-speaker EER, not by train-CV.
- Learned layer weights (MHFA-style) didn't consistently beat the best single layer in Serrano et al. Not worth the time.

### 3.2 Windowing
- **3-4 s windows, 50% hop.** ASVspoof systems standardize on ~4 s (64,600 samples). 3 s keeps us real-time (40 ms/window on MPS). Mean-pool frames inside the window; std-pooling adds a little.
- **Gate windows with Silero VAD** (already in the stack): drop windows with <50% speech, both at train and inference. This kills the silence shortcut and saves compute.
- **Split by speaker (and by clip) before windowing.** Never let windows of the same clip land in train and test.

### 3.3 Normalization (important)
- **`microsoft/wavlm-base-plus` has `do_normalize: false`**, so raw amplitude goes into the model and **loudness differences between ElevenLabs downloads and our mic recordings are visible to the classifier.** Before feature extraction: resample to 16 kHz mono -> trim DC -> **loudness-normalize every window to the same RMS (e.g. -23 dBFS) or zero-mean/unit-variance** (what `wavlm-large` / XLS-R do with `do_normalize: true`). Apply identically at inference.
- Feature side: `StandardScaler` fit on train folds only, then `LogisticRegression(C in {0.01,0.1,1,10}, class_weight="balanced", max_iter=5000)`. Pascu et al. found weaker regularization (larger C) better with big backbones; with few speakers, let CV choose.

### 3.4 Calibration and decision rule
- LR outputs are roughly calibrated in-domain but **shift across channels**. Set the operating threshold on the **held-out speaker + replayed clips** at a target false-alarm rate on real speech (bank use case: false accusations are costly; aim for <=2-5% FPR on reals), not at 0.5.
- If time: Platt-scale (1-D LR on the logit) using the held-out set.
- Show an **"uncertain" band** (e.g. 0.35-0.65, or high prediction entropy) in the UI instead of a hard flip. Pascu et al. show entropy-based rejection improves accuracy on accepted samples.

### 3.5 Quick wins (ranked by value per minute)
1. **Record real AND fake through the demo channel** (laptop/phone speaker -> mic, same room). Replay alone took the best ASVspoof model from 4.7% to 18.2% EER (ReplayDF). 30 min of recording beats any augmentation.
2. **Score aggregation across windows:** per-call score = mean of window **logits** over VAD-speech windows (or EMA with alpha~0.3 for the live gauge). Alert only when **>=3 of the last 5 windows** exceed threshold. This removes single-window flicker on stage.
3. **Augment both classes identically** (online or 2x offline copies), chosen at random per clip:
   - phone band: resample 8 kHz -> 16 kHz, optional G.711 mu-law (`ffmpeg -ar 8000 -acodec pcm_mulaw`);
   - lossy codec: MP3 32-64 kbps, Opus 16-24 kbps (`ffmpeg -c:a libopus -b:a 16k`);
   - noise at SNR 5-20 dB (room tone recorded at the venue, or pink noise);
   - reverb: convolve with a synthetic exponential-decay RIR (RT60 0.2-0.6 s) or `pyroomacoustics`.
   The AntiDeepfake authors found RawBoost alone insufficient for real-world audio; codec+noise+RIR is the practical minimum.
4. **Layer averaging (3-6)** instead of last layer: free.
5. **Second backbone** (wavlm-large or AntiDeepfake-Small features) + score fusion (average logits): ~45 min including extraction, typically a few EER points OOD.
6. **External fakes for diversity:** gary `el_*` (173) + Mendeley ElevenLabs (335) + 1-2 MLAAD model folders, matched by LibriSpeech/ITW reals pushed through the **same** preprocessing and augmentation.

### 3.6 Feature extraction sketch (MPS)
```python
import torch, numpy as np
from transformers import AutoModel
m = AutoModel.from_pretrained("microsoft/wavlm-base-plus").to("mps").eval()
@torch.inference_mode()
def layer_feats(win16k: np.ndarray) -> np.ndarray:          # win: 3 s float32 @16 kHz
    x = (win16k - win16k.mean()) / (win16k.std() + 1e-7)       # loudness-invariant
    hs = m(torch.from_numpy(x)[None].to("mps"), output_hidden_states=True).hidden_states
    return torch.stack([h[0].mean(0) for h in hs]).cpu().numpy()  # [13, 768]; cache this
# feature for LR: layer_feats(w)[3:7].mean(0)  -> sweep alternatives on cached arrays
```
Use `sklearn.model_selection.GroupKFold(groups=speaker)` for every CV number we report.

---

## 5. Demo-embarrassment pitfalls and 1-hour tests

Run all of these as one `scripts/shortcut_audit.py` (~1 h to write and run). Each test has a **pass criterion**.

| # | Pitfall | Why it happens here | Test (minutes) | Pass if | Fix |
|---|---|---|---|---|---|
| 1 | **Silence shortcut** | Real recordings have leading/trailing room tone; TTS output starts on speech. ASVspoof19 models got 15% EER from leading-silence duration alone and RawNet2 went 3.6% -> 15.5% EER when silence was trimmed ([Müller et al. 2021](https://arxiv.org/abs/2106.12914); [Zhang et al. 2023](https://arxiv.org/abs/2309.11827)) | (a) LR on [duration, leading-silence, trailing-silence] only (10 min). (b) Score windows of **pure non-speech** from each class (5 min) | (a) AUC < 0.65. (b) non-speech windows score ~0.5 or are VAD-dropped | Silero VAD trim + speech-only windows |
| 2 | **Loudness / gain** | wavlm-base-plus doesn't normalize input; ElevenLabs output is mastered loud, mic audio isn't | LR on [RMS, peak, crest factor] (5 min). Also re-score real clips at -10 dB and +10 dB gain (5 min) | AUC < 0.65; score moves < 0.1 | Per-window normalization (§3.3) |
| 3 | **Sample rate / bandwidth** | ElevenLabs = 44.1/22.05 kHz MP3; mics = 48 kHz; Mendeley = 22.05 kHz. After resampling, energy above ~7-11 kHz still differs | LR on [spectral rolloff 95%, energy fraction > 4 kHz, > 7 kHz] (10 min) | AUC < 0.7 | Resample all to 16 kHz; randomly apply 8 kHz phone-band to both classes; optionally low-pass everything at 7 kHz |
| 4 | **MP3 = fake** | All ElevenLabs downloads are MP3; our reals are WAV. Classifier learns "codec pre-echo / 16 kHz cutoff" | **Flip test:** MP3-encode real holdout clips at 128 kbps (and decode fakes to WAV) and re-score (10 min) | Mean P(fake) on MP3'd reals rises < 0.1 | Transcode everything through the same MP3 round-trip, or augment both classes with MP3/Opus |
| 5 | **Speaker identity leakage** | Clones are *of team members*; if the same speakers' reals and fakes are in train, the model can learn "Alice-real vs Alice-clone timbre drift" or simply who | (a) Leave-one-speaker-out EER vs random-split EER (10 min). (b) LR on **ECAPA speaker embeddings** alone (already have SpeechBrain) (10 min) | (a) gap < ~5 EER points. (b) ECAPA-LR clearly worse than WavLM-LR | Holdout whole speakers; add more speakers via ElevenLabs library voices + external sets |
| 6 | **Script / content leakage** | Fakes read the bank script, reals were casual chat (or vice versa); upper SSL layers encode content | Score real clips reading the *fraud script* and fake clips reading casual text (10 min recording) | Verdict unchanged | Same scripts for both classes; use lower layers |
| 7 | **Channel mismatch on stage** | Demo plays the clone through a speaker into the mic; training fakes were clean files. ReplayDF: replayed fakes pass as real | Record 10 real + 10 fake **through the exact demo rig**; score them (20 min) | All 10 fakes flagged, <=1 real flagged | Add replayed clips to training (both classes); tune threshold on them |
| 8 | **Unseen generator** | Judge asks "what about not-ElevenLabs?" | Score macOS `say`, Kokoro/Piper, gary `hu_*`/`sp_*`, ITW spoof slice (10 min) | Report the honest number on a slide | Present as "generalization result", not a claim |
| 9 | **False positive on a real person** | Accent, phone speaker, noisy venue, someone with a cold | Two non-team people speak live at the venue (5 min) | Score below threshold for all windows after aggregation | k-of-n rule + uncertain band; threshold at low FPR |
| 10 | **Flicker / cold start** | First MPS inference ~1 s; single-window spikes | Run each demo call 5x (master plan gate) | Same verdict 5/5 | Warm-up at startup; k-of-n aggregation; EMA gauge |

**One-line rule:** any single "dumb" feature (duration, silence, RMS, bandwidth, codec, speaker embedding) with speaker-grouped AUC > ~0.7 means the dataset leaks. Fix data before touching the model.

---

## Do this tonight (ordered, ~5.5 h of ML time)

1. **Data hygiene pipeline (20 min).** One function used everywhere (train, eval, live): any input -> 16 kHz mono -> DC removal -> **MP3 round-trip for every file, real or fake** -> Silero-VAD trim -> per-window zero-mean/unit-variance. `labels.csv` with `speaker`, `source`, `channel`. Splits by speaker, before windowing.
2. **Record the demo channel (40 min).** Per teammate: ~10 real + ~10 ElevenLabs-clone clips played **through the exact demo speaker->mic rig**, reading the **same scripts** (bank script + casual). Plus 2 minutes of venue room tone for noise aug. This set is both training data and the honest eval.
3. **Pull small external sets (30 min, in background while recording).** `garystafford` `fake/el_*` (173 ElevenLabs) + `fake/hu_*`,`fake/sp_*` (unseen-TTS test); Mendeley ElevenLabs/Respeecher zip (600); LibriSpeech test-clean (reals); ITW 150+150 via the range-request script; `behavioralsignals` demo (22). All go through step 1.
4. **Baselines on the eval set (30 min).** `mo-thecreator` (chart point 1) and `Speech-Arena-2025/DF_Arena_500M_V_1` zero-shot (chart point 2; if remote code breaks on transformers 5.19 within 20 min, drop it). Append to `results/history.csv`.
5. **Cache features (60 min).** All 13 hidden states of `wavlm-base-plus` **and** a stronger backbone (`microsoft/wavlm-large` or `facebook/wav2vec2-xls-r-300m`) for 3 s windows / 1.5 s hop, clean + 1 augmented copy per window (random of: 8 kHz phone band, Opus 16k, noise SNR 5-20 dB, synthetic RIR), applied to both classes.
6. **Train + select (45 min).** StandardScaler + LogisticRegression, GroupKFold by speaker; sweep layer (single 2-8, avg 3-6) x C x backbone; pick by **held-out-speaker + replay-set EER**; fuse with DF_Arena logit if it helps; set the threshold at <=5% false alarms on real speech; define an "uncertain" band.
7. **Shortcut audit (60 min).** Run §5 tests 1-7 (dumb-feature LRs, gain test, MP3 flip test, ECAPA-only LR, leave-one-speaker-out gap, demo-rig replay). Any AUC > 0.7 -> fix data, retrain (step 6 is minutes on cached features).
8. **Wire into live pipeline + demo gate (30 min).** VAD-gated 3 s windows every 1 s, mean of logits / EMA gauge, alert on >=3 of last 5 windows, MPS warm-up at startup. Both demo calls give the same verdict 5/5 runs; screenshot the history chart (mo-thecreator -> DF_Arena -> ours, with unseen-TTS and replay rows).

---

## Sources

- ASVspoof 5 overview (2026): https://arxiv.org/html/2601.03944v1 ; database paper: https://arxiv.org/pdf/2408.08739 ; data: https://zenodo.org/records/14498691
- Reality Defender ASVspoof5 submission: https://arxiv.org/pdf/2410.07379 ; Vicomtech-UGR: https://deepfake-demo.aisec.fraunhofer.de/related_work/2408.10361
- In-the-Wild (Müller et al. 2022): https://arxiv.org/abs/2203.16263 ; dataset: https://huggingface.co/datasets/mueller91/In-The-Wild , https://deepfake-total.com/in_the_wild
- Speech DF Arena (2025/2026): https://arxiv.org/html/2509.02859v1 ; leaderboard: https://huggingface.co/spaces/Speech-Arena-2025/Speech-DF-Arena
- Speech Anti-Spoofing Arena checkpoint mirrors: https://huggingface.co/SpeechAntiSpoofingBenchmarks
- DF_Arena_500M_V_1: https://huggingface.co/Speech-Arena-2025/DF_Arena_500M_V_1 ; RAPTOR paper: https://arxiv.org/abs/2603.06164
- Deepfake-Eval-2024: https://arxiv.org/pdf/2503.02857v3
- Podonos / Resemble vendor benchmarks (biased): https://www.podonos.com/blog/deepfake-audio-benchmark , https://resemble.ai/resources/audio-deepfake-detection-benchmark-results-how-8-systems-performed-in-2026
- Pascu et al., frozen SSL + LR (Interspeech 2024): https://arxiv.org/abs/2309.05384 , https://www.isca-archive.org/interspeech_2024/pascu24_interspeech.html
- Browser-plugin truncated SSL + logistic (2026): https://arxiv.org/abs/2606.30780 , https://github.com/OctavianPascu97/Audio-Deepfakes-Browser-Plugin
- NII AntiDeepfake post-training (2025): https://arxiv.org/html/2506.21090v4 ; https://github.com/nii-yamagishilab/AntiDeepfake ; https://huggingface.co/nii-yamagishilab/wav2vec-large-anti-deepfake-nda ; https://huggingface.co/nii-yamagishilab/wav2vec-small-anti-deepfake ; ONNX: https://huggingface.co/SpeechAntiSpoofingBenchmarks/Wav2Vec2-Small-AntiDeepfake
- Layer-wise SSL analysis: El Kheir et al. 2025 https://arxiv.org/abs/2502.03559 ; Serrano et al. 2025 https://arxiv.org/html/2509.12003v1
- Replay attacks / ReplayDF (Interspeech 2025): https://arxiv.org/abs/2505.14862 , https://deepfake-demo.aisec.fraunhofer.de/replay_df
- Silence shortcut: https://arxiv.org/abs/2106.12914 ; https://arxiv.org/abs/2309.11827
- Checkpoints: https://huggingface.co/mo-thecreator/Deepfake-audio-detection ; https://huggingface.co/garystafford/wav2vec2-deepfake-voice-detector ; https://huggingface.co/Gustking/wav2vec2-large-xlsr-deepfake-audio-classification ; https://huggingface.co/MelodyMachine/Deepfake-audio-detection-V2
- Datasets: https://huggingface.co/datasets/garystafford/deepfake-audio-detection ; https://data.mendeley.com/datasets/79g59sp69z/1 ; https://huggingface.co/datasets/mueller91/MLAAD ; https://huggingface.co/datasets/behavioralsignals/deepfake-detection-demo ; https://datashare.ed.ac.uk/handle/10283/3336 ; https://zenodo.org/record/5642694 ; https://www.openslr.org/12
- Preprocessor configs (do_normalize): https://huggingface.co/microsoft/wavlm-base-plus/blob/main/preprocessor_config.json , https://huggingface.co/microsoft/wavlm-large/blob/main/preprocessor_config.json
