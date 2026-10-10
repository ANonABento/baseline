# Open multimodal (audio + text) emotion datasets: tonight-downloadable check

Date: 2026-10-10. Status: WEB SURVEY, exploratory. Nothing downloaded, no load snippet executed. Builds on `docs/research/open_datasets.md` (not repeated). Pages were read through a summarising fetch tool, so licence strings are the tool's quotation; a human re-reads before any commercial step. NOTE: deliverable placed under `research/evidence/` (my write scope), not `docs/research/`; the lead can copy it.

| Dataset | HF id / URL (opened) | Licence as shown | Size | Labels | Real emotional transcript text | Speaker ids for disjoint split | Gated | Audio |
|---|---|---|---|---|---|---|---|---|
| MELD (audio mirror) | `ajyy/MELD_audio` (derived from `zrr1999/MELD_Text_Audio`, not opened) | tag gpl-3.0; card licence field "[More Information Needed]" | 1.53 GB (repo) | 7 emotions (anger, disgust, sadness, joy, neutral, surprise, fear) + 3 sentiment | YES (TV dialogue `text` column) | NOT exposed by the loader script (cols: text, path, audio, emotion, sentiment). CSV headers not seen: UNVERIFIED | No notice | Yes, 16 kHz mono extracted from mp4 |
| CREMA-D (HF mirror) | `AbstractTTS/CREMA-D` | no licence on page (ODbL per GitHub, from prior survey) | 606 MB, 7.44k rows | 6 emotions, per-clip float scores, `major_emotion`, gender | NO: 12 fixed sentences (`transcription`) | YES via filename prefix (`1001_DFA_ANG_XX.wav` -> actor 1001), no column | No notice | Yes |
| EmoV-DB (HF mirror) | `CLAPv2/EmoV_DB` | none ("No dataset card yet"); another page says unique non-commercial licence (search snippet) | 3.11 GB, 6.89k rows; train 4.83k / val 621 / test 1.45k | neutral, amused, sleepy, disgusted, angry | Partly: sentence text in `text`/`raw_text`; read, acted | Not a column (gender only). Original has 4 speakers: UNVERIFIED here | No notice | Yes |
| EMO-DB | `renumics/emodb` | none on page (source emodb.bilderbar.info) | 46.9 MB, 535 rows, one `train` split | 7 emotions, age, gender | NO text field | NO speaker field | No notice | Yes |
| TESS | no standalone HF parquet found; bundled in `JesseHuang922/VoxSentinel_Emotion_Base` (zip; viewer error; not opened) | UNVERIFIED (prior survey: CC BY-NC-ND) | UNVERIFIED | 7 | NO (carrier phrase) | 2 speakers only | UNVERIFIED | UNVERIFIED |
| SAVEE | no HF mirror found; prior survey: official page failed cert check | UNVERIFIED | UNVERIFIED (480 utt, 4 speakers per paper snippet) | 7 | NO | 4 speakers | UNVERIFIED | UNVERIFIED |
| ESD | not re-opened; prior survey: emailed licence form | research-only form | n/a | 5 | fixed sentences | yes | YES (form) | n/a |
| CMU-MOSEI / MOSI | github.com/CMU-MultiComp-Lab/CMU-MultimodalSDK ; MultiBench `pliang279/MultiBench` (pointer only) | repo MIT; dataset licence NOT STATED on page | not stated | sentiment/emotion | transcripts as features (not confirmed on page) | not confirmed | Not gated, but SDK-download hosts not named: UNVERIFIED | NO raw audio/video ("we are not allowed to share the raw videos"); only pre-extracted features. Unusable for waveform encoders |
| GoEmotions | `google-research-datasets/go_emotions` | apache-2.0 (tag + card) | configs `simplified` 54.3k rows (43,410 / 5,426 / 5,427), `raw` 211k | 27 emotions + neutral, multi-label ids | YES (Reddit comments), text only | `raw` has author, rater_id (author-disjoint split possible) | No notice | none |
| DailyDialog | `roskoN/dailydialog` | "CC BY-NC-SA 4.0 ... may not be adopted for commercial use" | 2.3 MB, 13,118 dialogues (11.1k/1k/1k) | per-utterance `emotions` ids 0-6, `acts` 1-4 (id meaning not on page: UNVERIFIED) | YES, dialogue text only | none | No notice | none |
| Scam/vishing call transcripts | none opened and confirmed open. Leads (search snippets only, UNVERIFIED): Kaggle "Scam and Non-Scam Call Conversation" (800 convs, IEEE Access paper); IEEE DataPort Korean voice-phishing set (augmented; login terms unknown); HF `bolewara/hinglish-scam-text-dataset` (3,787 written messages, not calls); HF `Shade63/scam-classification-multiclass` (short texts, unconfirmed) | UNVERIFIED | 800 convs / 3,787 msgs | scam vs non-scam | transcripts, no audio | none known | UNVERIFIED | none |

Not opened: HF `zrr1999/MELD_Text_Audio`, MELD official site, any Kaggle page, CREMA-D official terms, SAVEE/TESS primary pages. Search found no open scam-call audio; IJCAI 2026 snippet says real fraud calls are hard to redistribute (privacy).

## Ranking for a 3 h laptop / one Colab GPU job (frozen encoders, train heads only)

Assumption (PREDICTION, not tested): frozen WavLM/wav2vec2-base + small text encoder, embeddings cached once; training of heads takes minutes, so extraction dominates.

1. **MELD_audio only, fused with GoEmotions text pretraining.** Only verified set with real emotional dialogue text AND audio, ungated, 1.53 GB. Text branch warm-started on GoEmotions (apache-2.0). Weakness: no speaker column in loader; official splits are by dialogue, main characters recur across splits, so NOT speaker-disjoint; report this. TV audio has laughter/music. Licence: gpl-3.0 tag on repo plus TV copyright question, human sign-off.
2. **MELD_audio + CREMA-D (audio-only auxiliary, speaker-disjoint by actor).** CREMA-D gives clean speaker-disjoint audio evaluation (91 actors per prior survey, ids from filenames) and arousal-like intensity structure; its fixed sentences add no text signal, so feed text branch a masked/neutral input or train the audio head only. Compare against MELD to measure acted-to-spontaneous gap. Licence ODbL (CREMA-D, not on mirror page) share-alike: sign-off.
3. **Acted audio bundle (CREMA-D + EmoV-DB + EMO-DB) + DailyDialog/GoEmotions text, trained as two separately supervised branches (no paired data).** Late fusion with no joint audio-text labels is weak; use only if MELD loading fails. Licences mixed, EmoV-DB non-commercial, DailyDialog NC-SA: research only.

Scam/content branch: nothing verified usable tonight. Treat as gap; do not train on unverified Kaggle/IEEE data without opening terms.

## Load snippets (ids verified to exist as pages; snippets NOT executed)

```python
from datasets import load_dataset
go   = load_dataset("google-research-datasets/go_emotions", "simplified")   # text, 27+neutral multi-label
dd   = load_dataset("roskoN/dailydialog")                                    # config "full" per page
crema = load_dataset("AbstractTTS/CREMA-D", split="train")                   # one split; actor = ex["file"].split("_")[0]
emov = load_dataset("CLAPv2/EmoV_DB")                                        # train/validation/test
emodb = load_dataset("renumics/emodb", split="train")                        # card's split='all' may be outdated
meld = load_dataset("ajyy/MELD_audio", trust_remote_code=True)               # uses MELD_audio.py script
```

MELD caveats: the HF page says the viewer is disabled because it needs a loading script (arbitrary code); newer `datasets` releases may refuse scripts (UNVERIFIED, test the pinned version). The fetch of `MELD_audio.py` suggested an audio-dict bug (`{"path": path, bytes: f.read()}`, key is the builtin `bytes`); this is one tool's reading, unconfirmed. Fallback: `huggingface_hub.snapshot_download("ajyy/MELD_audio", repo_type="dataset")` then read `train.csv` and `archive/*.tar.gz` yourself; check CSV headers for a Speaker column first.

## Gaps and conflicts
- No dataset here has dimensional arousal (SAM/valence-arousal); arousal must be derived from categories or CREMA-D intensity. PREDICTION-level only.
- No opened source gives delivery-style labels (pace, hesitation, etc.). Delivery style would be derived from acoustics/ASR, not labelled data.
- CREMA-D licence: mirror silent, GitHub says ODbL (prior survey); EmoV-DB licence conflicts/unknown; EMO-DB licence not on mirror.
- MOSEI: tool summary of repo; dataset terms and download hosts unread.

## Search log
2026-10-10, WebSearch (standard): "huggingface dataset phishing vishing scam call transcripts conversation dataset" (9 results; no open call-audio set); "huggingface datasets EmoDB SAVEE TESS EmoV-DB emotion speech audio parquet" (10 results; found EmoV-DB and a bundle). WebFetch of 10 HF/GitHub pages above. Inclusion: ungated, downloadable without signing, audio and/or text emotion labels. Retraction check: not applicable (datasets, no papers cited as evidence).
