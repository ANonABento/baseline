# Open speech datasets for the voice + content signal model

Date: 2026-10-10. Status: LITERATURE/WEB SURVEY, exploratory. Nothing downloaded or trained.
Scope: supports `docs/finetuning_plan.md` outputs S1 (emotion/arousal), S2 (change vs own baseline), S3 (delivery markers), S4 (answer responsiveness). No deception corpora or labels are used or recommended.

How to read: every row below comes from a page I opened this session via a summarising fetch tool (so licence "quotes" are the tool's quotation of the page, not a byte-exact copy; a human should re-read the licence before any commercial step). `UNVERIFIED` = I could not open a primary page, or the page did not state it. Items marked "(search snippet)" come from a web-search result, not an opened page.

## 1. Summary table

| Dataset | Access without signed agreement/fee? | Licence (as quoted) | Commercial | Size (as stated) |
|---|---|---|---|---|
| LibriSpeech | Yes, OpenSLR direct | "CC BY 4.0" | OK (attribution) | dev-clean 337M, test-clean 346M, train-clean-100 6.3G, 360 23G, other-500 30G |
| AMI (HF `edinburghcstr/ami`) | Yes, HF, not gated (no gating noted) | "CC-BY-4.0" | OK (attribution) | 29 GB total (HF) |
| RAVDESS | Yes, Zenodo | "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International"; commercial licence purchasable via ravdess@gmail.com | NO (NC, SA) | 24.8 GB all; Audio Speech 1,440 files, 215 MB |
| CREMA-D | UNCLEAR (GitHub summary says a Google form; HF parquet mirror is open) | "made available under the Open Database License" (ODbL 1.0) | ODbL allows commercial use but is share-alike/attribution for the database; mirror card has no licence text | ZIP ~24 MB compressed, ~163 MB uncompressed (GitHub); HF parquet 606 MB; full git clone ~7.55 GB |
| TESS | Yes (TSpace / Scholars Portal Dataverse, no login noted) | "Creative Commons license Attribution-NonCommercial-NoDerivatives 4.0 International" | NO (NC, ND) | UNVERIFIED (not stated) |
| EmoV-DB | Yes, OpenSLR 115 | UNVERIFIED (LICENSE.md not displayed to me) | UNVERIFIED | 20 archives, 29M-193M each, about 1.9 GB total |
| MELD | Yes, HF (not gated) | GPL-3.0 (repo and HF card); no stated NC clause on GitHub | Licence says GPL-3.0, but content is Friends TV clips: copyright of source is a separate question, UNVERIFIED | 11.8 GB (HF) |
| ESD | NO: "complete a License and send it to zhoukun@u.nus.edu"; "can only be used for research purpose" | MIT mentioned plus research-only licence form | NO | not stated |
| MSP-Podcast | NO: signed data transfer agreement (329 academic groups, per paper); page `ecs.utdallas.edu` failed certificate check, so access terms come from the paper and a search snippet | audio mostly CC ("90.86% CC-BY, 5.59% CC-BY-SA, 2.88% Public Domain"); corpus licence: academic free, commercial US$8,000 (search snippet, UNVERIFIED) | Only with paid commercial licence | not stated |
| IEMOCAP | NO: "fill out an electronic release form"; terms in a PDF I did not open | UNVERIFIED | UNVERIFIED (assume no) | not stated |
| CMU-MOSEI | Features only via SDK; "we are not allowed to share the raw videos" | repo footer MIT; dataset terms UNVERIFIED | UNVERIFIED | not stated |
| Switchboard-1 (LDC97S62) | NO: LDC membership or non-member purchase, price behind login | "LDC User Agreement for Non-Members" | fee/terms UNVERIFIED | ~260 h, ~2,400 calls, 543 speakers |
| SUSAS (LDC99S78) | NO: LDC fee behind login | "LDC User Agreement for Non-Members" | UNVERIFIED | 32 speakers, >16,000 utterances |
| BESST (stress, Czech) | NO: registration, then signed licence PDF returned by email | licence text not shown | UNVERIFIED | not stated |
| Common Voice | NO longer on HF: page says "Effective October 2025, Mozilla Common Voice datasets are now exclusively available through Mozilla Data Collective"; HF repo is empty | not on page (historically CC0, UNVERIFIED) | UNVERIFIED | n/a |
| People's Speech | Yes, HF, no gating noted | "CC-BY and CC-BY-SA subsets" (configs `cc-by-clean`, `cc-by-sa-clean`, etc.) | CC-BY configs OK; CC-BY-SA share-alike | not stated in GB; ~8 M rows |
| VoxCeleb1/2 | NO: form required for download | exact licence not shown on page | UNVERIFIED | n/a |
| EMOVOME (Spanish) | Partly: CSVs/features/transcripts open; raw audio needs signed agreement | "Creative Commons Attribution 4.0 International (CC-BY-4.0) applies to all data except raw audio files" | non-audio files OK; audio no | 1.3 GB zip (without restricted audio) |
| EmoDB | download link exists (search snippet); terms UNVERIFIED (official site not opened) | UNVERIFIED | UNVERIFIED | 535 utterances (search snippet) |
| SAVEE | page failed certificate check; UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |

## 2. Per-dataset notes

**LibriSpeech** (openslr.org/12). "approximately 1000 hours of 16kHz read English speech", from LibriVox audiobooks, segmented and aligned. Speaker count not stated on the page I opened. Speaker IDs and transcripts: standard in the corpus but not stated on the page (UNVERIFIED from this page). Read speech only, no emotion labels. Fit: (1) many utterances per speaker, yes (per-speaker structure UNVERIFIED on page); (2) none; (3) the *read* class; (4) none (not conversational).

**AMI** (groups.inf.ed.ac.uk/ami and HF `edinburghcstr/ami`). "100 hours of meeting recordings", about two-thirds scripted scenario (role-play design team), rest natural meetings; orthographic transcripts plus dialog acts and other annotations; "47 unique speaker IDs" in the HF transcribed portion; configs `ihm` (headset mic, ~134,000 rows) and `sdm` (distant mic); 29 GB. Participants "mostly non-native speakers". Licence: "released publicly under the Creative Commons Attribution 4.0 International Licence (CC BY 4.0)" (some annotations excluded per the page). No emotion/arousal labels stated on either page. Fit: (1) good, many turns per speaker within a meeting and across meetings (cross-meeting speaker reuse UNVERIFIED); (2) none, would need pseudo-labels from an emotion model (PREDICTION); (3) spontaneous side of read vs spontaneous (scenario meetings are partly role-played); (4) good for turn-taking, responsiveness proxies via dialog acts.

**RAVDESS** (zenodo.org/records/1188976). 24 actors, 7,356 files in total (speech and song, audio and video); speech emotions neutral, calm, happy, sad, angry, fearful, surprise, disgust, two intensities, two lexically matched statements, acted. Audio speech 1,440 files, 215 MB. Fit: (1) 60 audio speech clips per actor, but same two sentences; (2) acted categorical plus intensity, no arousal scale on the page; (3) none; (4) none. Non-commercial and share-alike: prototype only.

**CREMA-D** (github.com/CheyneyComputerScience/CREMA-D). 7,442 clips, 91 actors, 12 sentences, six emotions, four intensity levels (Low/Medium/High/Unspecified), crowd ratings in audio-only, visual-only and audiovisual ("95% of the clips have more than 7 ratings"). No arousal dimension mentioned. Acted. Fit: (1) about 80 clips per actor (7,442/91, my arithmetic), same 12 sentences; (2) categorical plus intensity; (3) none; (4) none. The GitHub page mention of a Google form is ambiguous; the HF mirror `confit/cremad-parquet` (606 MB, 7,442 samples, no README, no gating noted) is not an official release, so verify provenance and licence.

**TESS.** 2,800 stimuli, two actresses, 200 target words in a carrier phrase, seven emotions, acted. Only 2 speakers; CC BY-NC-ND. Fit: poor on all four; skip.

**EmoV-DB.** 4 English speakers; emotions neutral, sleepiness, anger, disgust, amused; acted; TextGrid annotations; about 1.9 GB. Licence not read. Fit: few speakers; low priority.

**MELD.** "more than 1400 dialogues and 13000 utterances from Friends TV series"; train 1,039 dialogues / 9,989 utterances / 260 speakers; dev 114 / 1,109 / 47; test 280 / 2,610 / 100; emotion (7) and sentiment labels; scripted TV, not spontaneous. Fit: (4) dialogue structure with transcripts; (2) categorical only; (1) weak (character IDs, TV audio with laughter/music). Licence GPL-3.0 does not settle rights in the underlying TV audio: flag for human.

**ESD.** 350 parallel utterances, 10 English plus 10 Mandarin speakers, five emotions, transcripts, acted. Needs emailed licence form, research only. Not tonight.

**MSP-Podcast** (arXiv 2509.09791). 409 h (407 h final), 3,641 speakers, v2.0 (September 2025); categorical (8 primary, 16 total) and dimensional labels, Self-Assessment Manikin 1-7 scales for valence, arousal ("1 (very calm) to 7 (very active)"), dominance; at least five raters per segment; spontaneous podcasts. Best fit to S1 by far (and the audEERING checkpoint in the plan was trained on it), but access is a signed agreement signed by an institution; commercial licence price UNVERIFIED. Not available tonight.

**IEMOCAP.** About 12 h, 10 actors, improvised and scripted dyadic sessions, categorical and dimensional labels, transcripts with word-level alignment. Electronic release form needed. Best conversational acted set but not tonight; commercial terms UNVERIFIED.

**CMU-MOSEI.** In-the-wild videos annotated for sentiment and emotion; raw video not shared, anonymised processed features only. No raw audio, so not usable for waveform encoders; licence UNVERIFIED.

**Switchboard, SUSAS.** LDC catalogue pages opened: paid/agreement access, prices behind login. SUSAS: 32 speakers, >16,000 utterances, 35 aircraft words, four stress domains, 8 kHz; the only stress-labelled set in this list but not free. Not usable tonight.

**BESST.** From a search result (not the page): 90 subjects, 16.9 h of clean Czech speech, cognitive stress via reading span task and physical stress via hand immersion, DOI 10.13164/data.fit.besst. The opened page showed access requires a form and a signed licence returned by email; content details were not on the page. Closest match to real (induced) stress with a within-speaker design (about 15 min of speech per participant, search snippet), but needs agreement and is Czech. Worth requesting for the post-hackathon phase; VOCE (public-speaking stress corpus, search snippet only) is UNVERIFIED.

**Common Voice, VoxCeleb, People's Speech.** Common Voice moved to Mozilla Data Collective (page statement above); read-aloud prompts, so not spontaneous either (UNVERIFIED on opened page). VoxCeleb: no emotion labels (EmoVoxCeleb labels were produced "using an automatic classifier"), form-gated, "Dataset Privacy Notice" exists; skip. People's Speech: 30,000+ h, no speaker IDs, so unusable for per-speaker baselines.

**EMOVOME.** 999 spontaneous Spanish voice messages, 100 speakers, expert and non-expert valence/arousal and categories, transcriptions. Spontaneous real-life speech with arousal labels, but raw audio needs a signed agreement from an institution and the language is Spanish. Open parts (labels, transcripts, eGeMAPS features) can be inspected tonight.

## 3. Recommended minimal set (downloadable tonight without signing anything)

| Model output | Dataset | Why | Commercial |
|---|---|---|---|
| S3 read vs spontaneous (and baseline structure) | LibriSpeech `dev-clean` (337M) / `train-clean-100` (6.3G) as **read**; AMI `ihm` (HF, CC-BY 4.0) as **spontaneous/conversational** | Gives a labelled read/spontaneous contrast with speaker IDs and transcripts. Caveat: corpus differences (recording channel, language background, microphones) are confounded with read vs spontaneous; do not claim the model detects reading from this alone | Both CC BY 4.0: OK with attribution |
| S2 per-speaker baseline | AMI `ihm` (several turns per speaker); LibriSpeech (many utterances per speaker) | Test mechanics of "delta vs own baseline"; there is no ground truth for stress in either | OK |
| S4 responsiveness / conversational content | AMI (dialog acts, turn structure; scenario meetings) | Only open, ungated, conversational set with transcripts | OK |
| S1 arousal/emotion | CREMA-D (ODbL; 91 actors, six emotions, intensity, crowd ratings) and RAVDESS (research only) for prototyping | Free and small. Both are acted and have only categorical or intensity labels, no arousal scale | CREMA-D: share-alike/ODbL obligations apply, human to review; RAVDESS: NO. If a commercial path is needed, MSP-Podcast commercial licence (UNVERIFIED price) or own recordings |

Download check before relying on any of this: CREMA-D official access path and licence on the mirror, and the AMI page not mentioning gating were taken from fetch summaries.

## 4. Honest limits

- Acted emotion is not real stress. CREMA-D, RAVDESS, TESS, EmoV-DB, ESD, EmoDB and IEMOCAP's scripted part are performed emotions; models trained on them capture how actors portray categories, and transfer to spontaneous or induced stress is not established by anything I opened.
- No opened open dataset provides stress-related change relative to the same speaker's baseline with ground truth. SUSAS and BESST are the candidates but are gated. S2 stays a HYPOTHESIS measured by manipulation checks on our own controlled recordings (plan sections 6 and 8).
- Read vs spontaneous from LibriSpeech vs AMI is confounded by corpus, channel and speaker population; hold out whole speakers and ideally add own recordings in both modes.
- "Arousal" from the open set is categorical or intensity only; dimensional arousal needs MSP-Podcast (agreement) or EMOVOME (agreement for audio).
- Licences: hackathon use of NC sets is research only. Anything going into a startup needs human sign-off in `docs/licences.md`. I did not read LICENSE.md for EmoV-DB, IEMOCAP's PDF, the CC BY-SA implications for People's Speech, or EmoDB/SAVEE terms.
- Deception corpora: deliberately not surveyed and not used.
- Sizes are only those stated on pages I opened; blank = not stated.
