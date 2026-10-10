"""Generate small demo clips with macOS `say` + ffmpeg into data/demo/.

Each clip is built sentence by sentence (one utterance per sentence, separated by
silence) and gets a timestamped sidecar transcript `<clip>.txt` that the stub STT
uses in replay/eval. Optional `<clip>.meta.json` carries stub detector hints.

Usage (from repo root):
    uv run --project backend python scripts/make_clips.py [--ffmpeg PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "demo"
SR = 16_000
GAP_S = 0.9

CLIPS: dict[str, dict] = {
    "benign_balance": {
        "voice": "Samantha",
        "lines": [
            "Hi, this is Margaret Chen, I'm calling about my checking account.",
            "I'd like to know my current balance, please.",
            "Also, could you tell me when my last deposit cleared?",
            "And what's the interest rate on my savings account these days?",
            "Wonderful, that's all I needed. Thank you so much.",
        ],
    },
    "takeover_clone": {
        "voice": "Samantha",
        "lines": [
            "Hi, this is Margaret Chen. I need to update the phone number on my account.",
            "I got a new phone, so please change my phone number and my email too.",
            "Once that's done, I need to wire nine thousand dollars to a new account today.",
            "It's urgent, it has to go out right now.",
            "And please don't call my old number, I don't have that phone anymore.",
        ],
        # Stub-only: lets the dashboard show a full red alert before the real spoof model lands.
        "meta": {
            "stub_hints": {
                "spoof": {"score": 0.88, "confidence": 0.8,
                          "reason": "[stub hint] synthetic-speech artifacts (placeholder until spoof model lands)"},
                "speaker": {"score": 0.1, "confidence": 0.8,
                            "reason": "[stub hint] voice matches enrolled customer (clone fools voice-ID)"},
            }
        },
    },
    "grandparent_vulnerable": {
        "voice": "Moira",
        "lines": [
            "Hello dear, this is Margaret Chen. I need to send some money today.",
            "My grandson was arrested and he needs bail money right away.",
            "His lawyer called me and said to wire eight thousand dollars.",
            "He told me not to tell anyone, he's so embarrassed.",
            "Can you please hurry, the lawyer is on the other line.",
        ],
    },
}


def tts(text: str, voice: str, ffmpeg: str, tmp: Path, idx: int) -> np.ndarray:
    aiff, wav = tmp / f"{idx}.aiff", tmp / f"{idx}.wav"
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(aiff), "-ac", "1", "-ar", str(SR),
                    "-sample_fmt", "s16", str(wav)], check=True)
    audio, sr = sf.read(str(wav), dtype="float32")
    assert sr == SR
    return audio


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ffmpeg", default=os.environ.get("FFMPEG", shutil.which("ffmpeg") or "/Users/bentomac/bin/ffmpeg"))
    ap.add_argument("--only", nargs="*", help="clip names to (re)build")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    gap = np.zeros(int(GAP_S * SR), dtype=np.float32)
    for name, spec in CLIPS.items():
        if args.only and name not in args.only:
            continue
        parts, lines = [gap[: SR // 2]], []
        t = len(parts[0]) / SR
        with tempfile.TemporaryDirectory() as td:
            for i, line in enumerate(spec["lines"]):
                a = tts(line, spec["voice"], args.ffmpeg, Path(td), i)
                lines.append(f"[{t:.2f}] {line}")
                parts += [a, gap]
                t += (len(a) + len(gap)) / SR
        audio = np.concatenate(parts)
        sf.write(str(OUT / f"{name}.wav"), audio, SR, subtype="PCM_16")
        (OUT / f"{name}.txt").write_text(
            "# Sidecar transcript for stub STT mode: [start_seconds] text\n" + "\n".join(lines) + "\n",
            encoding="utf-8")
        if "meta" in spec:
            (OUT / f"{name}.meta.json").write_text(json.dumps(spec["meta"], indent=2) + "\n", encoding="utf-8")
        print(f"wrote {name}.wav ({len(audio) / SR:.1f}s)")


if __name__ == "__main__":
    main()
