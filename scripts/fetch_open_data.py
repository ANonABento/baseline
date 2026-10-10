"""Fetch small subsets of open datasets into data/external/ (gitignored) and record a manifest.

Currently: RAVDESS speech audio (Zenodo 1188976, CC BY-NC-SA 4.0, RESEARCH ONLY, md5-checked) and AMI headset-mix shards from Hugging Face `edinburghcstr/ami` (CC-BY-4.0, not gated).
Each parquet shard holds utterance-level rows with audio, meeting_id, speaker_id, begin/end time and text.
Licence notes: docs/licences.md. No participant recordings are made or used.

Usage (repo root):
    uv run --project backend python scripts/fetch_open_data.py ami --shards train-00000-of-00042 train-00001-of-00042 validation-00000-of-00005
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/external"
AMI_REPO = "edinburghcstr/ami"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_ami(shards: list[str], config: str) -> None:
    from huggingface_hub import hf_hub_download

    dest = OUT / "ami" / config
    dest.mkdir(parents=True, exist_ok=True)
    entries = []
    for shard in shards:
        rel = f"{config}/{shard}.parquet"
        path = Path(hf_hub_download(AMI_REPO, rel, repo_type="dataset", local_dir=OUT / "ami"))
        entries.append({"file": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha256(path)})
        print(f"ok {rel} {path.stat().st_size / 1e6:.0f} MB")
    manifest = OUT / "ami" / "MANIFEST.json"
    manifest.write_text(json.dumps({"repo": AMI_REPO, "licence": "cc-by-4.0 (HF tag)", "config": config, "files": entries}, indent=1))
    print(f"wrote {manifest.relative_to(ROOT)}")


RAVDESS_URL = "https://zenodo.org/records/1188976/files/Audio_Speech_Actors_01-24.zip?download=1"
RAVDESS_MD5 = "bc696df654c87fed845eb13823edef8a"  # from the Zenodo record API


def fetch_ravdess() -> None:
    import urllib.request
    import zipfile

    dest = OUT / "ravdess"
    dest.mkdir(parents=True, exist_ok=True)
    zpath = dest / "Audio_Speech_Actors_01-24.zip"
    if not zpath.exists():
        urllib.request.urlretrieve(RAVDESS_URL, zpath)
    md5 = hashlib.md5(zpath.read_bytes()).hexdigest()
    if md5 != RAVDESS_MD5:
        raise SystemExit(f"md5 mismatch for {zpath.name}: {md5} != {RAVDESS_MD5}")
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(dest / "speech")
    n = len(list((dest / "speech").rglob("*.wav")))
    (dest / "MANIFEST.json").write_text(json.dumps(
        {"source": "zenodo.org/records/1188976", "licence": "CC BY-NC-SA 4.0 (research only, not shippable)", "md5": md5, "wav_files": n}, indent=1))
    print(f"ok ravdess {n} wavs, md5 verified")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ravdess")
    a = sub.add_parser("ami")
    a.add_argument("--config", default="ihm", choices=["ihm", "sdm"])
    a.add_argument("--shards", nargs="+", required=True, help="e.g. train-00000-of-00042")
    args = ap.parse_args()
    if args.cmd == "ravdess":
        fetch_ravdess()
    if args.cmd == "ami":
        fetch_ami(args.shards, args.config)


if __name__ == "__main__":
    sys.exit(main())
