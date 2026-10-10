"""Offline evaluation: run every labeled clip through the full pipeline, print per-module and
end-to-end accuracy, and append a timestamped row to results/history.csv.

labels.csv columns: file,speaker,is_synthetic,is_fraud,condition,notes[,expected_customer][,is_customer]
  file               path relative to the labels file (e.g. `margaret_clone_01.wav`, `../demo/x.wav`)
  speaker            who is actually speaking (free text, e.g. `margaret`, `moira_tts`)
  is_synthetic       1/0 (true/false/yes/no) - ground truth for the spoof module
  is_fraud           1/0 - ground truth for the fraud analyzer (script matches a fraud pattern)
  condition          free text bucket for the breakdown (clean, noisy, phone_codec, unseen_tts, ...)
  expected_customer  OPTIONAL. Customer id the caller claims to be; it is set as the active
                     customer for the call, so speaker verification compares against
                     data/enroll/<expected_customer>.npy (scripts/enroll.py). Empty = CUSTOMER_ID.
  is_customer        OPTIONAL. 1 if the voice is the expected customer's voice (a voice clone of
                     the customer counts as 1: speaker-verify measures voice identity, catching
                     clones is the spoof module's job), 0 for a different person. If the column
                     is missing/empty but expected_customer is set, truth = (speaker ==
                     expected_customer, case-insensitive). Rows with neither are not scored
                     for the speaker module.

Predictions: a module is "positive" when its signal fires in fusion (score >= threshold and
confidence >= min); for speaker that means "voice does not match". End-to-end is positive when
the alert level is caution or high; its truth is is_synthetic OR is_fraud OR (speaker truth
known and not the customer). Stub `.meta.json` hints are always ignored here.

When a real STT provider is active and a `<clip>.txt` sidecar transcript exists, the word
error rate against it is reported (wer column). The history row records which providers were
actually used (after any fallback to stubs).

Usage (repo root):
    uv run --project backend python scripts/eval.py --note "pretrained spoof baseline"
    uv run --project backend python scripts/eval.py --labels path/to/labels.csv --no-log
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
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
    "timestamp", "git_sha", "n_files", "spoof_acc", "fraud_acc", "speaker_acc", "e2e_acc", "false_alarm_rate",
    "miss_rate", "wer", "mean_latency_ms", "mean_utt_ms", "wall_s", "stt", "llm", "providers", "note",
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


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("-", " ")).split()


def wer(hyp: str, ref: str) -> float | None:
    """Word error rate (Levenshtein over normalised words)."""
    h, r = _words(hyp), _words(ref)
    if not r:
        return None
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return round(d[len(h)] / len(r), 3)


def reference_transcript(wav: Path) -> str | None:
    txt = wav.with_suffix(".txt")
    if not txt.exists():
        return None
    lines = [re.sub(r"^\[[0-9.]+\]\s*", "", ln.strip()) for ln in txt.read_text(encoding="utf-8").splitlines()]
    return " ".join(ln for ln in lines if ln and not ln.startswith("#"))


def speaker_truth(r: dict) -> bool | None:
    """True = voice is NOT the expected customer (what a firing speaker signal claims)."""
    is_cust = parse_bool(r.get("is_customer"))
    if is_cust is not None:
        return not is_cust
    exp, spk = (r.get("expected_customer") or "").strip(), (r.get("speaker") or "").strip()
    if exp and spk:
        return spk.lower() != exp.lower()
    return None


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
        expected = (r.get("expected_customer") or "").strip()
        res = await analyze_wav(path, settings, use_stub_hints=False, customer_id=expected)
        ref = reference_transcript(path) if not res.used_sidecar and res.providers.get("stt") != "stub" else None
        spk = res.signals.get("speaker", {})
        out.append({
            "file": r["file"], "condition": (r.get("condition") or "").strip() or "-",
            "is_synthetic": parse_bool(r.get("is_synthetic")), "is_fraud": parse_bool(r.get("is_fraud")),
            "speaker_mismatch": speaker_truth(r),
            "spoof_pred": "spoof" in res.fired, "fraud_pred": "fraud" in res.fired,
            "speaker_pred": "speaker" in res.fired,
            "speaker_score": spk.get("score") if spk.get("confidence") else None,
            "spoof_score": res.signals.get("spoof", {}).get("score"),
            "alert": res.alert_level, "trust": round(res.trust, 1), "latency": res.mean_latency_ms,
            "utt_ms": [t["total_ms"] for t in res.utterance_timings if t.get("audio_s")],
            "wer": wer(res.transcript, ref) if ref else None,
            "sidecar": res.used_sidecar, "providers": res.providers,
        })
    return out


def migrate_history(path: Path) -> None:
    """Rewrite an existing history.csv whose header predates HISTORY_FIELDS (new columns empty)."""
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames == HISTORY_FIELDS:
            return
        rows = list(reader)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") or "" for k in HISTORY_FIELDS})


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

    print(f"\n{'file':34} {'cond':10} syn fraud spkX | spoof fraud spkX alert   trust  p_fake spk_risk   wer")
    for r in results:
        b = lambda v: "-" if v is None else ("1" if v else "0")  # noqa: E731
        f = lambda v: "    -" if v is None else f"{v:5.2f}"  # noqa: E731
        print(f"{Path(r['file']).name[:34]:34} {r['condition'][:10]:10}  {b(r['is_synthetic'])}    {b(r['is_fraud'])}"
              f"    {b(r['speaker_mismatch'])}  |   {b(r['spoof_pred'])}     {b(r['fraud_pred'])}    {b(r['speaker_pred'])}"
              f"  {r['alert']:7} {r['trust']:5}  {f(r['spoof_score'])}    {f(r['speaker_score'])} {f(r['wer'])}")

    spoof = [(r["spoof_pred"], r["is_synthetic"]) for r in results if r["is_synthetic"] is not None]
    fraud = [(r["fraud_pred"], r["is_fraud"]) for r in results if r["is_fraud"] is not None]
    speaker = [(r["speaker_pred"], r["speaker_mismatch"]) for r in results if r["speaker_mismatch"] is not None]
    scored = [r for r in results
              if r["is_synthetic"] is not None or r["is_fraud"] is not None or r["speaker_mismatch"] is not None]
    e2e = [(r["alert"] != "none", bool(r["is_synthetic"]) or bool(r["is_fraud"]) or bool(r["speaker_mismatch"]))
           for r in scored]
    negatives = [p for p, t in e2e if not t]
    positives = [p for p, t in e2e if t]
    far = round(sum(negatives) / len(negatives), 3) if negatives else None
    miss = round(sum(not p for p in positives) / len(positives), 3) if positives else None

    print(f"\nPer-module accuracy (n={len(results)}):")
    print(f"  spoof    {fmt(acc(spoof))}   (vs is_synthetic, n={len(spoof)})")
    print(f"  fraud    {fmt(acc(fraud))}   (vs is_fraud, n={len(fraud)})")
    print(f"  speaker  {fmt(acc(speaker))}   (fires = voice mismatch, vs not-the-expected-customer, n={len(speaker)})")
    wers = [r["wer"] for r in results if r["wer"] is not None]
    mean_wer = round(sum(wers) / len(wers), 3) if wers else None
    if wers:
        print(f"  stt      WER {mean_wer:.1%} vs <clip>.txt references (n={len(wers)})")
    print(f"End-to-end (alert>=caution vs synthetic/fraud/impostor): {fmt(acc(e2e))}"
          f"  false-alarm {fmt(far)}  miss {fmt(miss)}")

    by_cond: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for r, pair in zip(scored, e2e):
        by_cond[r["condition"]].append(pair)
    if len(by_cond) > 1:
        print("By condition (end-to-end):")
        for c, pairs in sorted(by_cond.items()):
            print(f"  {c:14} {fmt(acc(pairs))}  n={len(pairs)}")

    lat = [r["latency"] for r in results if r["latency"]]
    mean_lat = round(sum(lat) / len(lat), 1) if lat else 0.0
    utt = [x for r in results for x in r["utt_ms"]]
    mean_utt = round(sum(utt) / len(utt), 1) if utt else 0.0
    settings = get_settings()
    used = results[0]["providers"]
    stt = used.get("stt", settings.stt_provider) + ("+sidecar" if any(r["sidecar"] for r in results) else "")
    if used.get("stt") == "mlx":
        stt += ":" + settings.stt_model.split("/")[-1]
    providers = f"vad={used.get('vad')} speaker={used.get('speaker')} spoof={used.get('spoof')}"
    print(f"Mean detector latency {mean_lat} ms, mean per-utterance total {mean_utt} ms (n={len(utt)}), wall {wall}s")
    print(f"Providers: stt={stt} llm={settings.resolved_llm_provider()} {providers}")

    if args.no_log:
        return 0
    row = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "git_sha": git_sha(), "n_files": len(results),
        "spoof_acc": acc(spoof), "fraud_acc": acc(fraud), "speaker_acc": acc(speaker), "e2e_acc": acc(e2e),
        "false_alarm_rate": far, "miss_rate": miss, "wer": mean_wer, "mean_latency_ms": mean_lat,
        "mean_utt_ms": mean_utt, "wall_s": wall, "stt": stt, "llm": settings.resolved_llm_provider(),
        "providers": providers, "note": args.note,
    }
    args.history.parent.mkdir(parents=True, exist_ok=True)
    migrate_history(args.history)
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
