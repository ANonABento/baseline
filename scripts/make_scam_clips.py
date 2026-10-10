"""Generate scam-style clips (ElevenLabs eleven_flash_v2_5) for the voices the live demo uses and append
them to data/eval/labels_scam.csv. Lines: data/eval/scam_lines.csv (dev/test split by sentence).
  ELEVENLABS_API_KEY=... uv run --project backend --extra ml python scripts/make_scam_clips.py"""

from __future__ import annotations

import csv
import os
import sys
import urllib.request
import json
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
VOICES = {"clone_kevin": "kHe5D7QBSu8PKLzFC8Hz", "roger": "CwhRBWXzGAHq8TQ4Fs17", "callum": "N2lVS1w4EtoT3dr4eOWO",
          "george": "JBFqnCBsd6RMkjVDRZzb", "sarah": "EXAVITQu4vr4xnSDxMaL"}
MODEL = "eleven_flash_v2_5"


def tts(key: str, vid: str, text: str) -> np.ndarray:
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format=pcm_16000",
                                 data=json.dumps({"text": text, "model_id": MODEL}).encode(),
                                 headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/pcm"})
    return np.frombuffer(urllib.request.urlopen(req, timeout=90).read(), "<i2").astype(np.float32) / 32768.0


def main() -> None:
    key = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("set ELEVENLABS_API_KEY")
    lines = list(csv.DictReader((ROOT / "data/eval/scam_lines.csv").open()))
    out_dir = ROOT / "data/eval/scam"
    out_dir.mkdir(exist_ok=True)
    rows = []
    for name, vid in VOICES.items():
        for ln in lines:
            rel = f"scam/{name}_{ln['id']}.wav"
            if not (ROOT / "data/eval" / rel).exists():
                sf.write(ROOT / "data/eval" / rel, tts(key, vid, ln["text"]), 16_000)
            rows.append({"file": rel, "speaker": f"el_{name}", "is_synthetic": 1, "is_fraud": 1, "condition": f"scam_{ln['split']}_{name}",
                         "notes": f"ElevenLabs {MODEL} voice {name}, line {ln['id']} ({ln['scenario']}, {ln['split']})", "expected_customer": "", "is_customer": ""})
    with (ROOT / "data/eval/labels_scam.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", len(rows), "rows")


if __name__ == "__main__":
    main()
