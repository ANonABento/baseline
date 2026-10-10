"""Fetch the public transcript sets used by scripts/eval_fraud.py (small, cached, retried).

Datasets (normalized to the eval JSONL schema: {id, label: scam|benign, scenario, turns:[{speaker,
text}], source, license}; speaker "customer" = the party the bank agent hears on the line, the
only side the fraud analyzer is fed by default):

  BothBosu/scam-dialogue  (Apache-2.0, 1,600 synthetic phone dialogues, 8 types, balanced)
      test split  -> data/text_eval/bothbosu_test.jsonl   ~150 balanced, stratified  (EVAL, committed)
      train split -> data/text_eval/bothbosu_dev.jsonl    ~200 balanced, stratified  (DEV: the only
                     set keyword tuning may look at)
      Mapping: the dialogue's "caller" (in scam rows: the scammer) -> "customer"; "receiver" ->
      "agent". I.e. we score what the person placing the call says, as if they had called the bank.

  Lakshan2003/customer_service_client_agent_conversations_40k_multi_task  (NO license on the card)
      -> data/text_eval/local/lakshan_banking.jsonl (gitignored; never commit). Random pages of the
      train split filtered to banking calls; every call is benign (label "benign").
      Mapping: "client" -> "customer", "agent" -> "agent".

Uses the public HF datasets-server rows API (no token, no `datasets` dependency). Raw pages are
cached under data/text_eval/cache/ (gitignored) so re-runs are offline.

Usage (repo root):
    python3 scripts/fetch_text_eval.py                 # everything
    python3 scripts/fetch_text_eval.py --only bothbosu
    python3 scripts/fetch_text_eval.py --only lakshan --lakshan-n 200
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "text_eval"
CACHE = OUT / "cache"
LOCAL = OUT / "local"
API = "https://datasets-server.huggingface.co/rows"
PAGE = 100
SEED = 13

BOTHBOSU = "BothBosu/scam-dialogue"
LAKSHAN = "Lakshan2003/customer_service_client_agent_conversations_40k_multi_task"
LAKSHAN_ROWS = 40000

BANKING = re.compile(
    r"\b(bank|banking|credit union|checking|savings account|debit card|credit card|wire|transfer|"
    r"overdraft|routing number|account balance|loan|mortgage|statement)\b",
    re.IGNORECASE,
)


def fetch_page(dataset: str, split: str, offset: int, length: int = PAGE, retries: int = 5) -> list[dict]:
    """One rows-API page, cached on disk. Retries with exponential backoff on network errors."""
    safe = dataset.replace("/", "__")
    path = CACHE / f"{safe}__{split}__{offset}_{length}.json"
    if path.exists():
        return json.loads(path.read_text())
    q = urllib.parse.urlencode({"dataset": dataset, "config": "default", "split": split,
                                "offset": offset, "length": length})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(f"{API}?{q}", timeout=30) as r:
                rows = [x["row"] for x in json.loads(r.read())["rows"]]
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rows))
            return rows
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
            last = e
            wait = 2 ** attempt
            print(f"  {dataset} {split}@{offset}: {e!r}; retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"giving up on {dataset} {split}@{offset}: {last!r}")


# ---------------------------------------------------------------- BothBosu

_TURN = re.compile(r"\b(caller|receiver)\s*:\s*", re.IGNORECASE)


def parse_bothbosu_dialogue(dialogue: str) -> list[dict]:
    """'caller: Hi ... receiver: Yes ...' -> [{speaker: customer|agent, text}]."""
    parts = _TURN.split(dialogue or "")
    turns = []
    # parts = [prefix, role, text, role, text, ...]
    for role, text in zip(parts[1::2], parts[2::2]):
        text = text.strip()
        if text:
            turns.append({"speaker": "customer" if role.lower() == "caller" else "agent", "text": text})
    return turns


def stratified_sample(rows: list[dict], n: int, seed: int = SEED) -> list[dict]:
    """Balanced by label, then round-robin across `type` inside each label."""
    rng = random.Random(seed)
    out = []
    for label in (1, 0):
        by_type: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            if int(r["label"]) == label:
                by_type[r["type"]].append(r)
        for v in by_type.values():
            rng.shuffle(v)
        want, types, i = n // 2, sorted(by_type), 0
        picked: list[dict] = []
        while len(picked) < want and any(by_type.values()):
            t = types[i % len(types)]
            if by_type[t]:
                picked.append(by_type[t].pop())
            i += 1
        out += picked
    return out


def bothbosu_records(rows: list[dict], split: str) -> list[dict]:
    recs = []
    for r in rows:
        recs.append({
            "id": f"bb_{split}_{r['_idx']}",
            "label": "scam" if int(r["label"]) == 1 else "benign",
            "scenario": r["type"],
            "turns": parse_bothbosu_dialogue(r["dialogue"]),
            "source": BOTHBOSU,
            "license": "Apache-2.0",
        })
    return recs


def fetch_bothbosu(test_n: int, dev_n: int) -> None:
    for split, total, n, name in (("test", 320, test_n, "bothbosu_test"), ("train", 1280, dev_n, "bothbosu_dev")):
        rows = []
        for off in range(0, total, PAGE):
            page = fetch_page(BOTHBOSU, split, off, min(PAGE, total - off))
            for i, r in enumerate(page):
                rows.append({**r, "_idx": off + i})
        recs = bothbosu_records(stratified_sample(rows, n), split)
        write_jsonl(OUT / f"{name}.jsonl", recs)


# ---------------------------------------------------------------- Lakshan (benign banking)

def lakshan_record(r: dict) -> dict | None:
    conv = r.get("conversation") or []
    text = " ".join(t.get("text", "") for t in conv)
    if not BANKING.search(text):
        return None
    turns = [{"speaker": "customer" if t.get("speaker") == "client" else "agent", "text": t.get("text", "").strip()}
             for t in conv if (t.get("text") or "").strip()]
    if not any(t["speaker"] == "customer" for t in turns):
        return None
    return {"id": f"lk_{r['conversation_id'][:12]}", "label": "benign", "scenario": "customer_service_banking",
            "turns": turns, "source": LAKSHAN, "license": "none (local only, do not commit)"}


def fetch_lakshan(n: int, max_pages: int = 30) -> None:
    rng = random.Random(SEED)
    offsets = rng.sample(range(0, LAKSHAN_ROWS, PAGE), max_pages)
    recs: list[dict] = []
    for off in offsets:
        if len(recs) >= n:
            break
        try:
            page = fetch_page(LAKSHAN, "train", off)
        except RuntimeError as e:
            print(f"  skip page: {e}", file=sys.stderr)
            continue
        for r in page:
            rec = lakshan_record(r)
            if rec:
                recs.append(rec)
    write_jsonl(LOCAL / "lakshan_banking.jsonl", recs[:n])


def write_jsonl(path: Path, recs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    labels = defaultdict(int)
    for r in recs:
        labels[r["label"]] += 1
    print(f"wrote {path.relative_to(ROOT)}: {len(recs)} ({dict(labels)})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["bothbosu", "lakshan"])
    ap.add_argument("--bothbosu-test-n", type=int, default=150)
    ap.add_argument("--bothbosu-dev-n", type=int, default=200)
    ap.add_argument("--lakshan-n", type=int, default=150)
    a = ap.parse_args()
    if a.only in (None, "bothbosu"):
        try:
            fetch_bothbosu(a.bothbosu_test_n, a.bothbosu_dev_n)
        except RuntimeError as e:
            print(f"BothBosu fetch failed: {e}", file=sys.stderr)
    if a.only in (None, "lakshan"):
        fetch_lakshan(a.lakshan_n)


if __name__ == "__main__":
    main()
