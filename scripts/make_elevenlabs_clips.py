"""Generate ElevenLabs flash-model clips (synthetic voices, NOT clones of any person) for the
spoof eval (workplan 1.2). Text sent to the API = public LibriSpeech transcripts only.

  ELEVENLABS_API_KEY=... uv run --project backend python scripts/make_elevenlabs_clips.py

The key is read from the environment only; never put it in a file or in git. Output: 16 kHz mono
WAV in data/eval/spoof/ (gitignored) and rows appended to data/eval/labels_spoof.csv
(condition=elevenlabs_flash). Same transcripts as existing real rows, so real vs fake is paired."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "data" / "eval" / "labels_spoof.csv"
N_VOICES = 4
N_CLIPS = 16


def call(path: str, key: str, body: dict | None = None, accept: str = "application/json") -> bytes:
    req = urllib.request.Request("https://api.elevenlabs.io" + path, headers={"xi-api-key": key, "Accept": accept,
                                 "Content-Type": "application/json"}, data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def transcript(utt_id: str) -> str:
    spk, chap, _ = utt_id.split("-")
    f = ROOT / "data/external/LibriSpeech/test-clean" / spk / chap / f"{spk}-{chap}.trans.txt"
    for line in f.read_text().splitlines():
        if line.startswith(utt_id + " "):
            return line.split(" ", 1)[1].capitalize()
    raise KeyError(utt_id)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="eleven_flash_v2_5")
    ap.add_argument("--voice-id", help="use this voice (e.g. a team clone) instead of 4 premade voices")
    ap.add_argument("--tag", default="", help="short voice label for filenames/labels when --voice-id is used")
    ap.add_argument("--condition", default="elevenlabs_flash")
    args = ap.parse_args()
    MODEL = args.model
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("set ELEVENLABS_API_KEY in the environment")
    rows = list(csv.DictReader(LABELS.open()))
    done = {r["file"] for r in rows}
    real = [r for r in rows if r["condition"] == "real_librispeech"][:N_CLIPS]
    voices = [] if args.voice_id else json.loads(call("/v1/voices", key))["voices"]
    premade = [{"voice_id": args.voice_id, "name": args.tag or "clone"}] if args.voice_id else [v for v in voices if v.get("category") == "premade"][:N_VOICES]
    if not premade:
        sys.exit("no premade voices visible to this key")
    out_rows = []
    for i, r in enumerate(real):
        utt = Path(r["file"]).stem.removeprefix("real_")
        v = premade[i % len(premade)]
        vname = v["name"].split(" - ")[0].strip()
        rel = f"spoof/el_{vname.lower()}_{MODEL.removeprefix('eleven_')}_{utt}.wav"
        if rel in done:
            continue
        pcm = call(f"/v1/text-to-speech/{v['voice_id']}?output_format=pcm_16000", key,
                   {"text": transcript(utt), "model_id": MODEL}, accept="audio/pcm")
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        sf.write(ROOT / "data" / "eval" / rel, audio, 16_000)
        out_rows.append({"file": rel, "speaker": f"el_{vname.lower()}", "is_synthetic": 1, "is_fraud": 0,
                         "condition": args.condition, "notes": f"ElevenLabs {MODEL} voice {vname}, same transcript as {utt}",
                         "expected_customer": "", "is_customer": ""})
    with LABELS.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writerows(out_rows)
    print(f"wrote {len(out_rows)} clips with voices {[v['name'] for v in premade]}")


if __name__ == "__main__":
    main()
