"""Enroll a customer's voiceprint for speaker verification (needs the `ml` extra).

Writes data/enroll/<customer_id>.npy (L2-normalised mean of ECAPA embeddings over ~4 s
chunks of every input file) and data/enroll/<customer_id>.json (metadata). The backend picks
it up for calls whose active customer is <customer_id> (CUSTOMER_ID default, or the WS
`{"type":"customer","customer_id":...}` / replay `customer_id` field). data/enroll/ is
gitignored: voiceprints are personal data.

Usage (repo root):
    uv run --project backend --extra ml python scripts/enroll.py CUST-004217 me_1.wav me_2.wav --name "Margaret Chen"
    # demo: synthesize enrollment speech with a macOS `say` voice (different text from the demo clips)
    uv run --project backend --extra ml python scripts/enroll.py CUST-004217 --say Samantha --name "Margaret Chen"

Use 20-60 s of the customer's natural speech, ideally over the same channel as the calls.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from ml import voiceprints  # noqa: E402
from ml.audio import read_audio  # noqa: E402
from settings import get_settings  # noqa: E402

SR = 16_000
SAY_TEXT = [
    "My name is on the account and I have banked with you for many years.",
    "I usually call on Tuesday mornings to check my statements and pay a few bills.",
    "The weather has been lovely lately, so I have been working in the garden.",
    "My daughter lives nearby and visits on weekends with the grandchildren.",
    "Please read the last four transactions back to me, slowly if you can.",
    "I prefer paper statements, but I am learning to use the mobile app.",
]


def say_to_wav(voice: str, out: Path) -> Path:
    """macOS `say` -> AIFF (libsndfile reads AIFF directly) -> 16 kHz mono WAV."""
    import soundfile as sf

    parts = []
    with tempfile.TemporaryDirectory() as td:
        for i, line in enumerate(SAY_TEXT):
            aiff = Path(td) / f"{i}.aiff"
            subprocess.run(["say", "-v", voice, "-o", str(aiff), line], check=True)
            parts += [read_audio(aiff, SR), np.zeros(int(0.5 * SR), np.float32)]
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), np.concatenate(parts), SR, subtype="PCM_16")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("customer_id")
    ap.add_argument("wavs", nargs="*", type=Path, help="enrollment recordings (any soundfile-readable format)")
    ap.add_argument("--name", default="", help="display name stored in the metadata")
    ap.add_argument("--say", metavar="VOICE", help="demo: synthesize enrollment audio with macOS `say -v VOICE`")
    ap.add_argument("--enroll-dir", type=Path, default=None, help="default: ENROLL_DIR setting (data/enroll)")
    args = ap.parse_args()

    s = get_settings()
    enroll_dir = args.enroll_dir or s.enroll_dir
    if not voiceprints.valid_customer_id(args.customer_id):
        ap.error(f"invalid customer id {args.customer_id!r} (letters, digits, _ . - only)")
    wavs = list(args.wavs)
    if args.say:
        wavs.append(say_to_wav(args.say, enroll_dir / f"{args.customer_id}_say_{args.say}.wav"))
    if not wavs:
        ap.error("give at least one WAV or --say VOICE")

    from ml.ecapa import EcapaEncoder, cosine

    t0 = time.perf_counter()
    enc = EcapaEncoder.get(s.speaker_model, s.pretrained_dir, s.speaker_device)
    print(f"loaded {s.speaker_model} in {time.perf_counter() - t0:.1f}s")
    embs, total_s, files = [], 0.0, []
    for w in wavs:
        audio = read_audio(w, SR)
        e = enc.embed_long(audio)
        print(f"  {w.name}: {len(audio) / SR:.1f}s -> {len(e)} segment(s)")
        if e:
            embs += e
            total_s += len(audio) / SR
            files.append(w.name)
    if not embs:
        print("no usable audio (need >= 1.5 s per file)")
        return 1
    E = np.stack(embs)
    mean = E.mean(axis=0)
    mean /= np.linalg.norm(mean)
    self_sim = [cosine(e, mean) for e in E]
    meta = {
        "customer_id": args.customer_id, "name": args.name, "model": s.speaker_model,
        "n_segments": len(embs), "audio_s": round(total_s, 1), "files": files,
        "segment_similarity_to_mean": {"min": round(min(self_sim), 3), "mean": round(float(np.mean(self_sim)), 3)},
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    out = voiceprints.save(enroll_dir, args.customer_id, mean, meta)
    print(f"saved {out} (+ .json): {len(embs)} segments, {total_s:.1f}s audio, "
          f"segment->mean similarity min {meta['segment_similarity_to_mean']['min']} "
          f"mean {meta['segment_similarity_to_mean']['mean']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
