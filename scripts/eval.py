"""Offline evaluation: run every labeled clip through the full pipeline, print per-module and
end-to-end accuracy, and append a timestamped row to results/history.csv.

labels.csv columns: file,speaker,is_synthetic,is_fraud,condition,notes
  file          path relative to the labels file (e.g. `margaret_clone_01.wav`, `../demo/x.wav`)
  is_synthetic  1/0 (true/false/yes/no) - ground truth for the spoof module
  is_fraud      1/0 - ground truth for the fraud analyzer (script matches a fraud pattern)
  condition     free text bucket for the breakdown (clean, noisy, phone_codec, unseen_tts, ...)

Predictions: a module is "positive" when its signal fires in fusion (score >= threshold and
confidence >= min). End-to-end is positive when the alert level is caution or high; its truth
is is_synthetic OR is_fraud. Stub `.meta.json` hints are always ignored here.

Usage (repo root):
    uv run --project backend python scripts/eval.py --note "pretrained spoof baseline"
    uv run --project backend python scripts/eval.py --labels path/to/labels.csv --no-log
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from pipeline import analyze_wav  # noqa: E402
from settings import get_settings  # noqa: E402

HISTORY_FIELDS = [
    "timestamp", "git_sha", "n_files", "spoof_acc", "fraud_acc", "e2e_acc", "false_alarm_rate",
    "miss_rate", "mean_latency_ms", "wall_s", "stt", "llm", "note",
]


def parse_bool(v: str | None) -> bool | None:
    if v is None:
        return None
    s = v.strip().lower()
    if s in {"1", "true", "yes", "y", "t"}:
        return True
    if s in {"0", "false", "no", "n", "f"}:
        return False
    return None


def git_sha() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def acc(pairs: list[tuple[bool, bool]]) -> float | None:
    return round(sum(p == t for p, t in pairs) / len(pairs), 3) if pairs else None


def fmt(x: float | None) -> str:
    return "  n/a" if x is None else f"{x:5.1%}"


def load_rows(labels: Path) -> list[dict]:
    if not labels.exists():
        return []
    with labels.open(newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("file") or "").strip() and not r["file"].startswith("#")]


async def run(rows: list[dict], base: Path) -> list[dict]:
    settings = get_settings()
    out = []
    for r in rows:
        path = (base / r["file"].strip()).resolve()
        if not path.exists():
            print(f"  ! missing audio, skipped: {r['file']}")
            continue
        res = await analyze_wav(path, settings, use_stub_hints=False)
        out.append({
            "file": r["file"], "condition": (r.get("condition") or "").strip() or "-",
            "is_synthetic": parse_bool(r.get("is_synthetic")), "is_fraud": parse_bool(r.get("is_fraud")),
            "spoof_pred": "spoof" in res.fired, "fraud_pred": "fraud" in res.fired,
            "speaker_score": res.signals.get("speaker", {}).get("score"),
            "alert": res.alert_level, "trust": round(res.trust, 1), "latency": res.mean_latency_ms,
            "sidecar": res.used_sidecar,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", type=Path, default=ROOT / "data" / "eval" / "labels.csv")
    ap.add_argument("--history", type=Path, default=ROOT / "results" / "history.csv")
    ap.add_argument("--note", default="", help="free-text note stored with the history row")
    ap.add_argument("--no-log", action="store_true", help="do not append to history.csv")
    args = ap.parse_args()

    rows = load_rows(args.labels)
    if not rows:
        print(f"No labeled clips found in {args.labels} (missing or empty). Nothing to evaluate; history not updated.")
        print("Add rows like: margaret_clone_01.wav,margaret,1,1,clean,elevenlabs clone takeover script")
        return 0

    t0 = time.perf_counter()
    results = asyncio.run(run(rows, args.labels.parent))
    wall = round(time.perf_counter() - t0, 2)
    if not results:
        print("No audio files from labels.csv were found on disk. History not updated.")
        return 0

    print(f"\n{'file':40} {'cond':12} syn fraud | spoof fraud alert   trust")
    for r in results:
        b = lambda v: "-" if v is None else ("1" if v else "0")  # noqa: E731
        print(f"{Path(r['file']).name[:40]:40} {r['condition'][:12]:12}  {b(r['is_synthetic'])}    {b(r['is_fraud'])}  |"
              f"   {b(r['spoof_pred'])}     {b(r['fraud_pred'])}  {r['alert']:7} {r['trust']:5}")

    spoof = [(r["spoof_pred"], r["is_synthetic"]) for r in results if r["is_synthetic"] is not None]
    fraud = [(r["fraud_pred"], r["is_fraud"]) for r in results if r["is_fraud"] is not None]
    e2e = [(r["alert"] != "none", bool(r["is_synthetic"]) or bool(r["is_fraud"])) for r in results
           if r["is_synthetic"] is not None or r["is_fraud"] is not None]
    negatives = [p for p, t in e2e if not t]
    positives = [p for p, t in e2e if t]
    far = round(sum(negatives) / len(negatives), 3) if negatives else None
    miss = round(sum(not p for p in positives) / len(positives), 3) if positives else None

    print(f"\nPer-module accuracy (n={len(results)}):")
    print(f"  spoof    {fmt(acc(spoof))}   (vs is_synthetic, n={len(spoof)})")
    print(f"  fraud    {fmt(acc(fraud))}   (vs is_fraud, n={len(fraud)})")
    sp = [r["speaker_score"] for r in results if r["speaker_score"] is not None]
    print(f"  speaker  n/a      (no identity-mismatch label yet; mean risk {sum(sp) / len(sp):.2f})" if sp else "  speaker  n/a")
    print(f"End-to-end (alert>=caution vs synthetic-or-fraud): {fmt(acc(e2e))}"
          f"  false-alarm {fmt(far)}  miss {fmt(miss)}")

    by_cond: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for r, pair in zip([r for r in results if r["is_synthetic"] is not None or r["is_fraud"] is not None], e2e):
        by_cond[r["condition"]].append(pair)
    if len(by_cond) > 1:
        print("By condition (end-to-end):")
        for c, pairs in sorted(by_cond.items()):
            print(f"  {c:14} {fmt(acc(pairs))}  n={len(pairs)}")

    lat = [r["latency"] for r in results if r["latency"]]
    mean_lat = round(sum(lat) / len(lat), 1) if lat else 0.0
    settings = get_settings()
    stt = settings.stt_provider + ("+sidecar" if any(r["sidecar"] for r in results) else "")
    print(f"Mean detector latency {mean_lat} ms/utterance, wall {wall}s, stt={stt}, llm={settings.resolved_llm_provider()}")

    if args.no_log:
        return 0
    row = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "git_sha": git_sha(), "n_files": len(results),
        "spoof_acc": acc(spoof), "fraud_acc": acc(fraud), "e2e_acc": acc(e2e),
        "false_alarm_rate": far, "miss_rate": miss, "mean_latency_ms": mean_lat, "wall_s": wall,
        "stt": stt, "llm": settings.resolved_llm_provider(), "note": args.note,
    }
    args.history.parent.mkdir(parents=True, exist_ok=True)
    new = not args.history.exists() or args.history.stat().st_size == 0
    with args.history.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HISTORY_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: ("" if v is None else v) for k, v in row.items()})
    print(f"Appended to {args.history.relative_to(ROOT) if args.history.is_relative_to(ROOT) else args.history}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
