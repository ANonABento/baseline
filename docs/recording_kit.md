# Recording kit: real voices for the spoof "real" class and enrollment (about 5 min per person)

Decision (Dae, 2026-10-10): the open-data-only rule is **lifted for Kevin's and one teammate's own voices**, for (a) the "real human mic" class in the spoof eval and (b) enrolling the customer voiceprint. Everything else in `recording_protocol.md` stays retired (no staged-pressure scenes, no stress labels). Fakes from the Kevin_1Shot clone were also approved by Dae (done: `results/spoof_per_clip_v3_2026-10-10.csv`).

## Before recording
No consent form needed (Dae approved Kevin's and his own recordings). Keep audio in `data/train/` (gitignored), out of cloud sync, and don't upload it anywhere.

## What to record (natural speech, your own voice, no persona needed)
Two channels, each as 16-bit mono WAV at 16 kHz or higher (QuickTime/Voice Memos then convert, or `ffmpeg`):
- **Laptop mic**, quiet room: A) 60 s answering free questions in your own words (what you did today, a recent meal, your commute); B) read these 8 sentences once, one clip per sentence if you can:
  1. "The weather this morning was cooler than I expected."
  2. "I need to check my account before I send anything."
  3. "Could you tell me what the charge on the statement is for?"
  4. "My grandson usually calls me on Sunday afternoons."
  5. "Please repeat that, I did not quite catch the last part."
  6. "I would rather call the bank back on the number I have."
  7. "Thank you, I will think about it and get back to you."
  8. "That does not sound right to me, so I will wait."
- **Demo channel**: same A and B through the browser mic exactly as the live demo takes it (`make dev-live`), saved by the app if it records, otherwise a second laptop-mic take.
Name files `data/train/real/<id>_<channel>_<take>.wav` (for example `kevin01_laptop_A1.wav`). Note device, room and distance in `data/train/real/NOTES.md`.

## After recording (V does this)
- Quality check: no clipping (peak below -1 dBFS), 16 kHz after resampling, at least 20 s per speaker for enrollment.
- Enroll the customer voice: `uv run --project backend --extra ml python scripts/enroll.py CUST-<id> data/train/real/kevin01_laptop_A1.wav ... --name "<display name>"` (voiceprints are gitignored personal data).
- Add eval rows to `data/eval/labels_spoof.csv` with `is_synthetic=0`, `condition=real_mic_<id>`, then re-run the spoof eval and report per-person results with N (2 people is not a validated held-out-speaker test; say so).
- Speaker check: clone vs real enrolled voice with `expected_customer` set and `is_customer=1` for both (the spoof module, not speaker verify, has to catch the clone).

## Limits to state
Two people, two channels, a few minutes each: this tests whether real mic audio is falsely flagged, not generalisation. Spoof results on LibriSpeech stay a proxy for everything else.
