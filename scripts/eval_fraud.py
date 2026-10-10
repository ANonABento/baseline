"""Transcript-level evaluation of the fraud analyzer: false-alarm rate on benign banking calls,
detection rate on scams, and time-to-alert, replaying each call turn by turn exactly as the live
pipeline would see it.

For every call, the caller's lines (speaker "customer" by default) are fed one at a time; after
each line the real FraudDetector assesses the rolling transcript so far and its DetectorResult
goes into a fresh Fusion (fraud is the only signal), giving the alert level the bank agent would
see at that moment. Nothing about the label is visible to the detector.

Datasets (data/text_eval/, see scripts/fetch_text_eval.py):
  held_out       held_out_bank.jsonl  42 hand-written bank calls: 21 scams + a benign twin for each.
                 HELD OUT: never tune prompts or keywords on it. Only read it to report numbers.
  bothbosu_test  BothBosu/scam-dialogue test split sample (Apache-2.0), balanced. Eval only.
  bothbosu_dev   BothBosu/scam-dialogue train split sample. The ONLY set keyword tuning may use.
  lakshan        local/lakshan_banking.jsonl, benign banking customer-service calls (no license,
                 fetched locally, gitignored). Pure false-alarm suite.
  <path>.jsonl   any file in the same schema.
Schema per line: {id, label: scam|benign, scenario, turns:[{speaker, text}], twin_of?, key_turn?}
  key_turn = index into turns of the critical request (the wire / the money ask), optional.

Metrics (per dataset):
  detect     scams whose alert reached caution or higher at any point            (recall)
  false_al   benign calls whose alert reached caution or higher                  (FP rate)
  strong     calls whose fraud score reached >= 0.8. Fusion only goes HIGH on >= 2 independent
             hard signals (voice + script), so a fraud-only replay caps at caution; "strong" is
             the fraud reading that would make HIGH together with any voice signal.
  tta        time-to-alert on detected scams: caller-turn number of the first caution (1-based),
             median; and as a fraction of the call's caller turns, mean
  pre_key    detected scams alerted at or before the key request line (held_out has key_turn)
  ms/call    mean wall time of all detector calls in one call (keywords: ~ms; LLM: network)

Engine: keywords when no LLM key resolves (stub) or with --provider keywords; otherwise the LLM
with keyword fallback on timeout/error (the fallback share is reported).

Usage (repo root):
    uv run --project backend python scripts/eval_fraud.py --note "keywords baseline"
    uv run --project backend python scripts/eval_fraud.py --dataset held_out --failures 10 --no-log
    uv run --project backend python scripts/eval_fraud.py --provider nebius --concurrency 4 --note "llm"
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from detectors.fraud import FraudDetector, result_from_assessment  # noqa: E402
from fusion import Fusion  # noqa: E402

DATA = ROOT / "data" / "text_eval"
HISTORY = ROOT / "results" / "fraud_history.csv"
DATASETS: dict[str, Path] = {
    "held_out": DATA / "held_out_bank.jsonl",
    "bothbosu_test": DATA / "bothbosu_test.jsonl",
    "bothbosu_dev": DATA / "bothbosu_dev.jsonl",
    "lakshan": DATA / "local" / "lakshan_banking.jsonl",
}
DEFAULT_DATASETS = ["held_out", "bothbosu_test", "lakshan"]
STRONG_SCORE = 0.8
LEVELS = {"none": 0, "caution": 1, "high": 2}

HISTORY_FIELDS = [
    "timestamp", "git_sha", "dataset", "n", "n_scam", "n_benign", "detection_rate", "false_alarm_rate",
    "precision", "strong_scam_rate", "strong_benign_rate", "median_alert_turn", "mean_alert_frac",
    "pre_key_rate", "mean_call_ms", "mean_turn_ms", "engine", "model", "llm_fallback_rate", "sides", "note",
]


# ---------------------------------------------------------------- loading

class DataError(ValueError):
    pass


def parse_record(obj: Any, where: str = "") -> dict:
    """Validate + normalize one transcript record. Raises DataError on bad input."""
    if not isinstance(obj, dict):
        raise DataError(f"{where}: record is not an object")
    label = str(obj.get("label", "")).strip().lower()
    if label in {"1", "fraud", "scam", "true"}:
        label = "scam"
    elif label in {"0", "benign", "legit", "false"}:
        label = "benign"
    else:
        raise DataError(f"{where}: label must be scam|benign, got {obj.get('label')!r}")
    turns = obj.get("turns")
    if not isinstance(turns, list) or not turns:
        raise DataError(f"{where}: turns must be a non-empty list")
    norm = []
    for i, t in enumerate(turns):
        if not isinstance(t, dict) or not isinstance(t.get("text"), str):
            raise DataError(f"{where}: turn {i} needs {{speaker, text}}")
        norm.append({"speaker": str(t.get("speaker", "customer")).strip().lower(), "text": t["text"]})
    key = obj.get("key_turn")
    if key is not None and not (isinstance(key, int) and 0 <= key < len(norm)):
        raise DataError(f"{where}: key_turn out of range")
    return {
        "id": str(obj.get("id") or where),
        "label": label,
        "scenario": str(obj.get("scenario") or "unknown"),
        "twin_of": obj.get("twin_of"),
        "key_turn": key,
        "turns": norm,
    }


def load_jsonl(path: Path) -> list[dict]:
    recs = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip() and not line.lstrip().startswith("//"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise DataError(f"{path.name}:{n}: bad JSON ({e})") from e
            recs.append(parse_record(obj, f"{path.name}:{n}"))
    return recs


def caller_utterances(rec: dict, sides: str = "customer") -> list[tuple[int, str]]:
    """(turn index, text) for the lines the analyzer hears. Turn index doubles as utterance id,
    so evidence utterance ids point back into rec["turns"]."""
    return [(i, t["text"]) for i, t in enumerate(rec["turns"])
            if t["text"].strip() and (sides == "all" or t["speaker"] == "customer")]


# ---------------------------------------------------------------- replay

@dataclass
class CallResult:
    id: str
    label: str
    scenario: str
    n_turns: int                      # caller turns fed
    alert_turn: int | None = None     # 1-based caller turn of first caution+
    max_level: str = "none"
    max_score: float = 0.0
    strong: bool = False
    trigger: dict | None = None       # top pattern at first alert: {id, quote, utterance_id}
    key_turn: int | None = None       # index into turns
    alert_utt: int | None = None      # turns index of the line that raised the alert
    engines: list[str] = field(default_factory=list)
    model: str | None = None
    call_ms: float = 0.0

    @property
    def alerted(self) -> bool:
        return LEVELS[self.max_level] >= LEVELS["caution"]

    @property
    def alert_frac(self) -> float | None:
        return round(self.alert_turn / self.n_turns, 3) if self.alert_turn and self.n_turns else None

    @property
    def pre_key(self) -> bool | None:
        if self.key_turn is None or not self.alerted or self.alert_utt is None:
            return None
        return self.alert_utt <= self.key_turn


def make_fusion() -> Fusion:
    try:
        from settings import get_settings

        s = get_settings()
        return Fusion(s.fire_threshold, s.fire_min_confidence)
    except Exception:
        return Fusion()


async def replay_call(det: FraudDetector, rec: dict, sides: str = "customer") -> CallResult:
    utts = caller_utterances(rec, sides)
    res = CallResult(rec["id"], rec["label"], rec["scenario"], len(utts), key_turn=rec.get("key_turn"))
    fusion = make_fusion()
    t0 = time.perf_counter()
    for k in range(len(utts)):
        a = await det.assess(utts[: k + 1])
        r = result_from_assessment(a, "fraud")
        res.engines.append(r.details.get("engine", "keywords"))
        res.model = res.model or r.details.get("model")
        res.max_score = max(res.max_score, r.score)
        fusion.update(r)
        level = fusion.alert_event().level
        if LEVELS[level] > LEVELS[res.max_level]:
            res.max_level = level
        if res.alert_turn is None and LEVELS[level] >= LEVELS["caution"]:
            res.alert_turn = k + 1
            res.alert_utt = utts[k][0]
            pats = r.details.get("patterns") or []
            if pats:
                p = pats[0]
                res.trigger = {"id": p.get("id"), "quote": p.get("quote"), "utterance_id": p.get("utterance_id")}
    res.call_ms = (time.perf_counter() - t0) * 1000
    res.strong = res.max_score >= STRONG_SCORE
    return res


async def run_dataset(det: FraudDetector, recs: list[dict], sides: str, concurrency: int = 1) -> list[CallResult]:
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(rec: dict) -> CallResult:
        async with sem:
            return await replay_call(det, rec, sides)

    return list(await asyncio.gather(*(one(r) for r in recs)))


# ---------------------------------------------------------------- metrics

def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def compute_metrics(results: list[CallResult]) -> dict[str, Any]:
    scams = [r for r in results if r.label == "scam"]
    benign = [r for r in results if r.label == "benign"]
    tp = sum(r.alerted for r in scams)
    fp = sum(r.alerted for r in benign)
    detected = [r for r in scams if r.alerted]
    keyed = [r for r in detected if r.pre_key is not None]
    turns_all = sum(r.n_turns for r in results)
    engines = Counter(e for r in results for e in r.engines)
    n_eng = sum(engines.values())
    return {
        "n": len(results),
        "n_scam": len(scams),
        "n_benign": len(benign),
        "detection_rate": _rate(tp, len(scams)),
        "false_alarm_rate": _rate(fp, len(benign)),
        "precision": _rate(tp, tp + fp) if scams else None,
        "strong_scam_rate": _rate(sum(r.strong for r in scams), len(scams)),
        "strong_benign_rate": _rate(sum(r.strong for r in benign), len(benign)),
        "median_alert_turn": statistics.median([r.alert_turn for r in detected]) if detected else None,
        "mean_alert_frac": round(statistics.mean([r.alert_frac for r in detected]), 3) if detected else None,
        "pre_key_rate": _rate(sum(bool(r.pre_key) for r in keyed), len(keyed)),
        "mean_call_ms": round(statistics.mean([r.call_ms for r in results]), 1) if results else None,
        "mean_turn_ms": round(sum(r.call_ms for r in results) / turns_all, 2) if turns_all else None,
        "llm_fallback_rate": _rate(engines.get("keywords", 0), n_eng) if engines.get("llm") else None,
        "engines": dict(engines),
    }


def per_scenario(results: list[CallResult]) -> dict[tuple[str, str], tuple[int, int]]:
    """(label, scenario) -> (alerted, total)."""
    out: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for r in results:
        out[(r.label, r.scenario)][0] += int(r.alerted)
        out[(r.label, r.scenario)][1] += 1
    return {k: (v[0], v[1]) for k, v in sorted(out.items())}


# ---------------------------------------------------------------- output

def pct(x: float | None) -> str:
    return "  -  " if x is None else f"{100 * x:5.1f}%"


def num(x: Any, nd: int = 1) -> str:
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def print_table(rows: list[tuple[str, dict]]) -> None:
    hdr = f"{'dataset':<14} {'n':>4} {'scam':>4} {'ben':>4}  {'detect':>6} {'false_al':>8} {'strongS':>7} {'strongB':>7}  {'tta_turn':>8} {'tta_frac':>8} {'pre_key':>7} {'ms/call':>8}"
    print(hdr)
    print("-" * len(hdr))
    for name, m in rows:
        print(f"{name:<14} {m['n']:>4} {m['n_scam']:>4} {m['n_benign']:>4}  {pct(m['detection_rate']):>6} "
              f"{pct(m['false_alarm_rate']):>8} {pct(m['strong_scam_rate']):>7} {pct(m['strong_benign_rate']):>7}  "
              f"{num(m['median_alert_turn']):>8} {pct(m['mean_alert_frac']):>8} {pct(m['pre_key_rate']):>7} "
              f"{num(m['mean_call_ms']):>8}")


def print_scenarios(name: str, results: list[CallResult]) -> None:
    sc = per_scenario(results)
    if len(sc) <= 1:
        return
    print(f"\n  {name} per scenario (alerted/total):")
    for (label, scen), (a, n) in sc.items():
        print(f"    {label:<6} {scen:<28} {a}/{n}")


def print_failures(name: str, results: list[CallResult], recs: dict[str, dict], k: int) -> None:
    fps = [r for r in results if r.label == "benign" and r.alerted]
    fns = [r for r in results if r.label == "scam" and not r.alerted]
    if fps:
        print(f"\n  {name} FALSE ALARMS ({len(fps)}):")
        for r in fps[:k]:
            t = r.trigger or {}
            print(f"    {r.id} [{r.scenario}] turn {r.alert_turn}/{r.n_turns} {t.get('id')}: \"{t.get('quote')}\"")
    if fns:
        print(f"\n  {name} MISSES ({len(fns)}):")
        for r in fns[:k]:
            rec = recs[r.id]
            line = rec["turns"][r.key_turn]["text"] if r.key_turn is not None else next(
                (t["text"] for t in rec["turns"] if t["speaker"] == "customer"), "")
            print(f"    {r.id} [{r.scenario}] max_score={r.max_score:.2f}: \"{line[:140]}\"")


def git_sha() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "backend", "scripts"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def history_row(dataset: str, m: dict, engine: str, model: str | None, sides: str, note: str,
                sha: str, ts: str) -> dict:
    row = {k: m.get(k) for k in HISTORY_FIELDS if k in m}
    row.update(timestamp=ts, git_sha=sha, dataset=dataset, engine=engine, model=model or "", sides=sides, note=note)
    return {k: ("" if row.get(k) is None else row.get(k)) for k in HISTORY_FIELDS}


def append_history(rows: list[dict], path: Path = HISTORY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- main

def build_detector(provider: str | None) -> tuple[FraudDetector, str]:
    """Returns (detector, engine label). provider: None = settings/env, "keywords" = no LLM."""
    if provider == "keywords":
        return FraudDetector(None), "keywords"
    from providers import make_llm
    from settings import Settings, get_settings

    s = Settings(llm_provider=provider) if provider else get_settings()
    llm = make_llm(s)
    if getattr(llm, "is_stub", False):
        return FraudDetector(llm, timeout_s=s.llm_timeout_s), "keywords"
    return FraudDetector(llm, timeout_s=s.llm_timeout_s), f"llm:{s.resolved_llm_provider()}"


def resolve_datasets(names: list[str]) -> list[tuple[str, Path]]:
    out = []
    for n in names:
        if n == "all":
            out += [(k, p) for k, p in DATASETS.items() if k != "bothbosu_dev"]
        elif n in DATASETS:
            out.append((n, DATASETS[n]))
        else:
            p = Path(n)
            out.append((p.stem, p if p.is_absolute() else ROOT / p))
    return out


async def amain(a: argparse.Namespace) -> int:
    det, engine = build_detector(a.provider)
    sha, ts = git_sha(), datetime.now().astimezone().isoformat(timespec="seconds")
    table, hist = [], []
    model_seen: str | None = None
    for name, path in resolve_datasets(a.dataset or DEFAULT_DATASETS):
        if not path.exists():
            print(f"[skip] {name}: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path} not found "
                  f"(run scripts/fetch_text_eval.py)")
            continue
        recs = load_jsonl(path)
        if a.limit:
            recs = recs[: a.limit]
        results = await run_dataset(det, recs, a.sides, a.concurrency)
        m = compute_metrics(results)
        model = next((r.model for r in results if r.model), None)
        model_seen = model_seen or model
        eng = engine + ("(all-fallback)" if engine.startswith("llm") and not m["engines"].get("llm") else "")
        table.append((name, m))
        hist.append(history_row(name, m, eng, model, a.sides, a.note, sha, ts))
        if a.verbose:
            print_scenarios(name, results)
        if a.failures:
            print_failures(name, results, {r["id"]: r for r in recs}, a.failures)
        if a.dump:
            dump = Path(a.dump)
            dump.parent.mkdir(parents=True, exist_ok=True)
            with dump.open("a", encoding="utf-8") as f:
                for r in results:
                    f.write(json.dumps({"dataset": name, **{k: v for k, v in r.__dict__.items() if k != "engines"},
                                        "alerted": r.alerted, "alert_frac": r.alert_frac}) + "\n")
    if not table:
        print("no datasets found")
        return 1
    print(f"\nengine={engine} model={model_seen or '-'} sides={a.sides} sha={sha}\n")
    print_table(table)
    if not a.no_log:
        append_history(hist)
        print(f"\nappended {len(hist)} row(s) to {HISTORY.relative_to(ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", action="append",
                    help="held_out | bothbosu_test | bothbosu_dev | lakshan | all | path.jsonl (repeatable)")
    ap.add_argument("--limit", type=int, default=0, help="first N calls per dataset")
    ap.add_argument("--provider", choices=["keywords", "stub", "auto", "nebius", "nvidia", "ollama"],
                    help="override LLM_PROVIDER; 'keywords' = no LLM at all")
    ap.add_argument("--sides", choices=["customer", "all"], default="customer",
                    help="feed only the caller's lines (what the product hears) or both sides")
    ap.add_argument("--concurrency", type=int, default=1, help="calls replayed in parallel (LLM runs)")
    ap.add_argument("--failures", type=int, default=0, help="print up to N false alarms and misses per dataset")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-scenario breakdown")
    ap.add_argument("--dump", help="append per-call results as JSONL to this path")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-log", action="store_true", help="don't append to results/fraud_history.csv")
    return asyncio.run(amain(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
