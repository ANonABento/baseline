"""Build the real-vs-synthetic spoof eval set (deterministic; seed recorded in the manifest).

Real:       LibriSpeech test-clean utterances (CC BY 4.0), speaker-disjoint sampling.
Synthetic:  (a) macOS `say` voices reading the SAME transcripts as the real clips,
            (b) pitch-shifted real clips (voice-changer artifact; label is_synthetic=1).
ElevenLabs clones and team recordings are NOT produced here (need the team key / consent);
add them as extra rows in data/eval/labels_spoof.csv with condition `elevenlabs_*` / `team_*`.

Prereq: data/external/test-clean.tar.gz extracted to data/external/LibriSpeech/test-clean
(https://www.openslr.org/resources/12/test-clean.tar.gz, md5 32fa31d27d2e1cad72775fee3f4849a9).

Usage (repo root):
    uv run --project backend --extra ml python scripts/build_eval_set.py
    uv run --project backend python scripts/eval.py --labels data/eval/labels_spoof.csv --note "..."
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from ml.audio import resample  # noqa: E402

SR = 16_000
LIBRI = ROOT / "data/external/LibriSpeech/test-clean"
OUT = ROOT / "data/eval/spoof"
SAY_VOICES = ["Samantha", "Daniel", "Karen", "Moira", "Rishi", "Kathy", "Ralph", "Fred"]
FIELDS = ["file", "speaker", "is_synthetic", "is_fraud", "condition", "notes", "expected_customer", "is_customer"]


def utterances(rng: random.Random, n_speakers: int, per_speaker: int, min_s: float, max_s: float):
    speakers = sorted(p.name for p in LIBRI.iterdir() if p.is_dir())
    rng.shuffle(speakers)
    picked = []
    for spk in speakers:
        cands = []
        for trans in sorted((LIBRI / spk).glob("*/*.trans.txt")):
            for line in trans.read_text().splitlines():
                uid, text = line.split(" ", 1)
                flac = trans.parent / f"{uid}.flac"
                info = sf.info(flac)
                if min_s <= info.duration <= max_s:
                    cands.append((spk, uid, text.capitalize(), flac))
        rng.shuffle(cands)
        if len(cands) >= per_speaker:
            picked.extend(cands[:per_speaker])
        if len({p[0] for p in picked}) >= n_speakers:
            break
    return picked


def to_16k_mono(path: Path) -> np.ndarray:
    audio, sr = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return resample(audio, sr, SR) if sr != SR else audio


def say_render(text: str, voice: str, dest: Path) -> None:
    subprocess.run(["say", "-v", voice, "-o", str(dest), f"--data-format=LEI16@{SR}", text], check=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261010)
    ap.add_argument("--speakers", type=int, default=20)
    ap.add_argument("--per-speaker", type=int, default=2)
    ap.add_argument("--pitch-semitones", type=float, default=4.0)
    args = ap.parse_args()
    import librosa

    rng = random.Random(args.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    rows, manifest = [], []
    for i, (spk, uid, text, flac) in enumerate(utterances(rng, args.speakers, args.per_speaker, 4.0, 12.0)):
        audio = to_16k_mono(flac)
        real = OUT / f"real_{uid}.wav"
        sf.write(real, audio, SR)
        rows.append([f"spoof/{real.name}", f"libri_{spk}", 0, 0, "real_librispeech", f"LibriSpeech {uid}", "", ""])

        voice = SAY_VOICES[i % len(SAY_VOICES)]
        fake = OUT / f"say_{voice.lower()}_{uid}.wav"
        say_render(text, voice, fake)
        rows.append([f"spoof/{fake.name}", f"say_{voice.lower()}", 1, 0, "say_tts", f"macOS say {voice}, same transcript as {uid}", "", ""])

        shifted = OUT / f"pitch_{uid}.wav"
        sf.write(shifted, librosa.effects.pitch_shift(audio, sr=SR, n_steps=args.pitch_semitones), SR)
        rows.append([f"spoof/{shifted.name}", f"libri_{spk}_pitch", 1, 0, "voice_changer_pitch",
                     f"{uid} pitch-shifted {args.pitch_semitones:+.1f} semitones", "", ""])
        manifest.append({"utterance": uid, "speaker": spk, "text": text, "voice": voice})

    labels = ROOT / "data/eval/labels_spoof.csv"
    with labels.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        w.writerows(rows)
    files = {r[0]: sha(ROOT / "data/eval" / r[0]) for r in rows}
    (OUT / "MANIFEST.json").write_text(json.dumps({
        "seed": args.seed, "source": "LibriSpeech test-clean md5 32fa31d27d2e1cad72775fee3f4849a9",
        "script": "scripts/build_eval_set.py", "args": vars(args), "utterances": manifest, "sha256_16": files,
    }, indent=1))
    n_real = sum(1 for r in rows if r[2] == 0)
    print(f"wrote {labels.relative_to(ROOT)}: {len(rows)} clips ({n_real} real, {len(rows) - n_real} synthetic)")


if __name__ == "__main__":
    main()
