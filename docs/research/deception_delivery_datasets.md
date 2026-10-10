# Deception / bluffing / delivery-mode datasets: open and ungated check
Date: 2026-10-10. Status: EXPLORATORY survey. Intended copy target: docs/research/deception_delivery_datasets.md (my write scope is research/evidence/ only; parent agent to copy).

## Search log
Tools: HF API (`huggingface.co/api/datasets/<id>`), page fetches, 5 web searches. Budget 15 calls, all used.
Queries: "DOLOS dataset deception audio ... license"; "Deal or No Deal ... deal_or_no_dialog"; "Diplomacy betrayal dataset It Takes Two to Lie ..."; "Real-life Trial ... Bag-of-Lies access"; "Werewolf game audio dataset ... Among Us OR Mafia". Criteria: no signed agreement, no emailed form, no fee; audio or text; ground-truth source stated.
Not opened (calls ran out): Box of Lies, MU3D, Bag-of-Lies, Real-life Trial host page, Idiap Wolf, TED-LIUM (HF API returned 401 for `LIUM/tedlium`), Common Voice, podcasts. Search snippets are marked SNIPPET = not a primary source.

## Table (OPENED = I opened the page/API this session)
| Dataset | Source (opened?) | Access / gated | Licence as written | Size | Audio | Ground truth: how obtained | Verdict |
|---|---|---|---|---|---|---|---|
| Diplomacy deception (Peskov 2020) | `community-datasets/diplomacy_detection` (OPENED API) | Ungated, parquet | `unknown` | train 189 / val 21 / test 42 rows (rows = conversations; 17,289 messages per SNIPPET of paper) | No (text) | `sender_labels` = sender's own intended truthfulness; `receiver_labels` = receiver's perceived truthfulness (incl. "noannotation"). Sender label is speaker self-report during game, not independently checked (from SNIPPET of paper; card has no description) | USE. Intent label vs perceived label both present |
| Deal or No Deal (Lewis 2017) | `mikelewis0/deal_or_no_dialog` (OPENED API) | Ungated, script-based (`deal_or_no_dialog.py`) | API: `cc-by-4.0`; SNIPPET of an older README said CC-by-NC: CONFLICT, check card | dialogues 10,095 / 1,052 / 1,087; self_play 8,172 | No | No deception label. Hidden information IS present: `input` (own values) and `partner_input` (partner's values) as {count,value} sequences, so stated-vs-true value claims can be checked against partner_input. Deriving a "bluff" label is HYPOTHESIS, needs our own parser | USE (labels must be built) |
| CraigslistBargain | `stanfordnlp/craigslist_bargains` (OPENED API) | Ungated, script-only | `unknown` | 5,247 / 597 val / 838 test | No | Card: annotations "machine-generated". Private seller/buyer target prices exist in the original paper: NOT verified on the card, UNVERIFIED | MAYBE (script-only, features not seen) |
| DOLOS (Guo ICCV 2023) | rose1.ntu.edu.sg/dataset/DOLOS (OPENED); GitHub README (OPENED) | NOT ungated: account + Release Agreement, then approval | Academic non-commercial only; no redistribution, derivatives or commercial use; videos fetched from YouTube yourself | 1,675 clips, 213 subjects (SNIPPET) | Via YouTube download; not confirmed in package | truth/deception per clip in Dolos.xlsx; gameshow, speaker states true/false about own life (design-verified by show, how checked UNVERIFIED) | EXCLUDED (agreement) |
| Real-life Trial (Perez-Rosas 2015) | Search SNIPPET only (Michigan resources page, SVC 2025 paper); host page not opened | SVC 2025 paper says an agreement must be signed (SNIPPET): treat as gated; UNVERIFIED | UNVERIFIED | UNVERIFIED | Video | Verdict/exoneration based (guilty vs not-guilty/exonerated) = outside-verified, but noisy (SNIPPET) | EXCLUDED pending verification |
| Bag-of-Lies, MU3D | Named in SVC 2025 SNIPPET only | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED, not usable tonight |
| Werewolf Among Us | arXiv 2212.08279 SNIPPET | Online agreement not to misuse (SNIPPET) | UNVERIFIED | UNVERIFIED | Yes (multimodal) | game roles = hidden ground truth (design) | EXCLUDED (agreement) |
| Idiap Wolf corpus | publications.idiap.ch SNIPPET | UNVERIFIED | UNVERIFIED | ~7 h (SNIPPET) | Yes | roles known to the game | UNVERIFIED |
| FanLang-9 (Chinese Werewolf) | arXiv 2402.02330 SNIPPET | No evidence it is public | UNVERIFIED | 6,000 h recorded, ~127 h annotated (SNIPPET) | Yes | UNVERIFIED | NOT AVAILABLE as far as seen |
| VoxPopuli | `facebook/voxpopuli` (OPENED API) | Ungated, parquet | `cc0-1.0` and `other` tags (the `other` terms not read) | `en` and `en_accented` configs, size tag 1M-10M rows (all configs) | Yes, with text | No delivery label on card. EU Parliament speech: mixture of prepared/spontaneous, undeclared (my background knowledge, UNVERIFIED here) | Only as "formal/prepared" pool, not a clean rehearsed label |
| TED-LIUM | `LIUM/tedlium` API 401 | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | Talks are prepared (background knowledge, UNVERIFIED) | UNVERIFIED |
| LibriSpeech (read) + AMI `ihm` (spontaneous) | From docs/research/open_datasets.md (prior session, not reopened) | Ungated | CC BY 4.0 both | see that file | Yes + text + speaker ids | Delivery mode = corpus identity, so channel/speaker/domain confounded | USE with confound caveat |
| (d) Question-answer / responsiveness labels | None opened | - | - | - | - | No dataset found with answer-responsiveness labels. AMI dialog acts only (prior file) | GAP |

## Perceived vs verified deception
- Perceived: Diplomacy `receiver_labels` (what the receiver thought).
- Speaker-reported intent, contemporaneous (not independent): Diplomacy `sender_labels`.
- Checkable against hidden information: Deal or No Deal (`partner_input`); needs a derived label (HYPOTHESIS).
- Outside-verified (verdicts): Real-life Trial (SNIPPET, gated, noisy).
- Design-known (game rules/roles): DOLOS, Werewolf, Idiap Wolf (all agreement-gated or unverified).

## Ranking for tonight, one RTX 5090 (all text-only except the delivery pair)
1. Diplomacy: text, ~250 conversation rows, trains in minutes with a small encoder. Tests sender-intent vs receiver-perception heads. Split by `game_id`.
2. Deal or No Deal: 12k dialogues; build a "stated-value inconsistent with partner_input" label (HYPOTHESIS). Check licence conflict first.
3. LibriSpeech vs AMI (+ VoxPopuli `en`): delivery-mode head on a wav2vec2/Whisper encoder; split by speaker; expect corpus-shortcut leakage, so match codec/loudness and report that.
4. CraigslistBargain: after opening the loader script to confirm private-price fields.
Not available tonight: any ungated deception dataset WITH audio. Audio deception heads would need own recordings or an agreement (human action).

## Load snippets (ids/configs from API only; NOT executed here)
```python
from datasets import load_dataset
d = load_dataset("community-datasets/diplomacy_detection")   # splits train/validation/test; columns messages, sender_labels, receiver_labels, speakers, game_id
vp = load_dataset("facebook/voxpopuli", "en", streaming=True)  # config 'en' exists per file list; column names UNVERIFIED
```
`mikelewis0/deal_or_no_dialog` (configs `dialogues`, `self_play`) and `stanfordnlp/craigslist_bargains` ship loader scripts; recent `datasets` versions may refuse scripts. No verified workaround; test before relying.

## Gaps and conflicts
- Deal or No Deal licence: cc-by-4.0 (API) vs CC-by-NC (SNIPPET of an older README).
- DOLOS audio inclusion unconfirmed; the lab says it does not host the videos.
- Real-life Trial, Bag-of-Lies, MU3D, Box of Lies, TED-LIUM, podcasts, Common Voice: not opened.
- Licence `unknown` on Diplomacy and Craigslist: human compliance review before any commercial use.
- Deception labels here are from games and negotiations, not commercial calls; transfer to the brief's targets is untested (HYPOTHESIS).

Sources: https://huggingface.co/api/datasets/community-datasets/diplomacy_detection ; https://huggingface.co/api/datasets/mikelewis0/deal_or_no_dialog ; https://huggingface.co/api/datasets/stanfordnlp/craigslist_bargains ; https://huggingface.co/api/datasets/facebook/voxpopuli ; https://rose1.ntu.edu.sg/dataset/DOLOS/ ; https://github.com/NMS05/Audio-Visual-Deception-Detection-DOLOS-Dataset-and-Parameter-Efficient-Crossmodal-Learning
