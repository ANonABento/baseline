"""Train our own spoof classifier: frozen WavLM embeddings -> logistic regression (needs the `ml` extra).

Master plan section 3: microsoft/wavlm-base-plus (frozen, MPS) mean-pooled over ~3 s windows,
StandardScaler + LogisticRegression on top. Hold out a WHOLE speaker for evaluation, or the
model learns *who* instead of *real vs fake*.

Input CSV (paths relative to the CSV):
    file,label,speaker
    team/kevin_01.wav,real,kevin
    clones/kevin_el_01.wav,fake,kevin
  label: fake/spoof/synthetic/1 vs real/bonafide/genuine/0. A data/eval-style `is_synthetic`
  column works instead of `label`. `speaker` is needed for --holdout-speaker / grouped splits.

Usage (repo root):
    uv run --project backend --extra ml python scripts/train_spoof.py data/train/spoof.csv --holdout-speaker kevin
    uv run --project backend --extra ml python scripts/train_spoof.py data/train/spoof.csv --phone-aug --refit-all

Evaluation split: --holdout-speaker S (repeatable) puts every file of S in the test set;
otherwise ~--test-frac of speakers (or files, if there is no speaker column) are held out.
Metrics are reported per window and per file (mean P(fake) over its windows). By default the
saved model is the one trained WITHOUT the held-out data (so the reported numbers describe
it); --refit-all retrains on everything before saving.

Output: models/spoof_lr.joblib (gitignored) = dict(pipeline, wavlm_model, layer, window_s,
hop_s, threshold, meta). joblib is pickle: only load files you trained yourself.
Use it with SPOOF_PROVIDER=wavlm (SPOOF_LR_PATH to point elsewhere).
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from ml.audio import read_audio, resample, windows  # noqa: E402
from settings import get_settings  # noqa: E402

SR = 16_000
FAKE = {"1", "fake", "spoof", "synthetic", "deepfake", "true", "yes"}
REAL = {"0", "real", "bonafide", "bona-fide", "genuine", "human", "false", "no"}


def parse_label(row: dict) -> int | None:
    v = (row.get("label") or row.get("is_synthetic") or "").strip().lower()
    return 1 if v in FAKE else 0 if v in REAL else None


def load_rows(csv_path: Path) -> list[dict]:
    rows = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            f = (r.get("file") or "").strip()
            if not f or f.startswith("#"):
                continue
            y = parse_label(r)
            if y is None:
                print(f"  ! no usable label, skipped: {f}")
                continue
            p = (csv_path.parent / f).resolve()
            if not p.exists():
                print(f"  ! missing audio, skipped: {f}")
                continue
            rows.append({"path": p, "file": f, "y": y, "speaker": (r.get("speaker") or "").strip()})
    return rows


def phone_codec(audio: np.ndarray) -> np.ndarray:
    """Cheap telephone-channel augmentation: band-limit via 8 kHz round trip."""
    return resample(resample(audio, SR, 8_000), 8_000, SR)


def eer(y: np.ndarray, p: np.ndarray) -> float | None:
    from sklearn.metrics import roc_curve

    if len(set(y.tolist())) < 2:
        return None
    fpr, tpr, _ = roc_curve(y, p)
    fnr = 1 - tpr
    i = int(np.nanargmin(np.abs(fnr - fpr)))
    return float((fpr[i] + fnr[i]) / 2)


def metrics(y: np.ndarray, p: np.ndarray, thr: float = 0.5) -> dict:
    from sklearn.metrics import roc_auc_score

    pred = (p >= thr).astype(int)
    out = {"n": int(len(y)), "n_fake": int(y.sum()), "acc": float((pred == y).mean()) if len(y) else None,
           "tp": int(((pred == 1) & (y == 1)).sum()), "fp": int(((pred == 1) & (y == 0)).sum()),
           "tn": int(((pred == 0) & (y == 0)).sum()), "fn": int(((pred == 0) & (y == 1)).sum())}
    if len(set(y.tolist())) == 2:
        out["auc"] = float(roc_auc_score(y, p))
        out["eer"] = eer(y, p)
    return out


def fmt_metrics(name: str, m: dict) -> str:
    s = f"  {name:16} n={m['n']:4d} (fake {m['n_fake']})  acc={m['acc']:.3f}" if m["acc"] is not None else f"  {name}: empty"
    if "auc" in m:
        s += f"  auc={m['auc']:.3f}  eer={m['eer']:.3f}"
    return s + f"  [tp {m['tp']} fp {m['fp']} tn {m['tn']} fn {m['fn']}]"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--holdout-speaker", action="append", default=[], help="speaker(s) used only for testing")
    ap.add_argument("--test-frac", type=float, default=0.25, help="held-out fraction when no --holdout-speaker")
    ap.add_argument("--window-s", type=float, default=3.0)
    ap.add_argument("--hop-s", type=float, default=1.5)
    ap.add_argument("--layer", type=int, default=-1, help="-1 = last hidden state, k = hidden_states[k]")
    ap.add_argument("--C", type=float, default=1.0, help="inverse L2 regularisation strength")
    ap.add_argument("--phone-aug", action="store_true", help="also train on 8 kHz round-trip copies")
    ap.add_argument("--refit-all", action="store_true", help="retrain on train+test before saving")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=None, help="default: SPOOF_LR_PATH (models/spoof_lr.joblib)")
    args = ap.parse_args()

    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    from ml.spoof_models import WavLMEmbedder

    s = get_settings()
    out_path = args.out or s.spoof_lr_path
    rows = load_rows(args.csv)
    if not rows:
        print("no usable rows")
        return 1

    # ---- split
    rng = np.random.default_rng(args.seed)
    hold = {h.lower() for h in args.holdout_speaker}
    if hold:
        unknown = hold - {r["speaker"].lower() for r in rows}
        if unknown:
            print(f"  ! holdout speaker(s) not in CSV: {sorted(unknown)}")
        test_mask = [r["speaker"].lower() in hold for r in rows]
        split_desc = f"held-out speaker(s): {sorted(hold)}"
    else:
        groups = sorted({r["speaker"] or r["file"] for r in rows})
        n_test = max(1, int(round(len(groups) * args.test_frac))) if len(groups) > 1 else 0
        test_groups = set(rng.permutation(groups)[:n_test].tolist())
        test_mask = [(r["speaker"] or r["file"]) in test_groups for r in rows]
        split_desc = f"random {'speaker' if any(r['speaker'] for r in rows) else 'file'}-grouped split ({n_test}/{len(groups)} held out)"
    for r, t in zip(rows, test_mask):
        r["test"] = t

    # ---- embeddings
    t0 = time.perf_counter()
    emb = WavLMEmbedder(s.wavlm_model, args.device, s.wavlm_safetensors_revision)
    print(f"loaded {s.wavlm_model} on {emb.device} in {time.perf_counter() - t0:.1f}s; {len(rows)} files, {split_desc}")
    t0 = time.perf_counter()
    n_win = 0
    for r in rows:
        audio = read_audio(r["path"], SR)
        wins = windows(audio, SR, args.window_s, args.hop_s, min_s=1.0)
        r["X"] = np.concatenate([emb.embed(wins[i:i + 8], layer=args.layer) for i in range(0, len(wins), 8)]) if wins else None
        if args.phone_aug and not r["test"] and wins:
            pw = windows(phone_codec(audio), SR, args.window_s, args.hop_s, min_s=1.0)
            r["X_aug"] = np.concatenate([emb.embed(pw[i:i + 8], layer=args.layer) for i in range(0, len(pw), 8)])
        n_win += len(wins)
    dt = time.perf_counter() - t0
    print(f"embedded {n_win} windows in {dt:.1f}s ({1000 * dt / max(n_win, 1):.0f} ms/window)")
    rows = [r for r in rows if r["X"] is not None]

    def stack(rs: list[dict], aug: bool = False) -> tuple[np.ndarray, np.ndarray]:
        Xs, ys = [], []
        for r in rs:
            for X in [r["X"]] + ([r["X_aug"]] if aug and "X_aug" in r else []):
                Xs.append(X)
                ys.append(np.full(len(X), r["y"]))
        return (np.concatenate(Xs), np.concatenate(ys)) if Xs else (np.zeros((0, 1)), np.zeros(0))

    train = [r for r in rows if not r["test"]]
    test = [r for r in rows if r["test"]]
    Xtr, ytr = stack(train, aug=args.phone_aug)
    if len(set(ytr.tolist())) < 2:
        print("training split needs both real and fake examples")
        return 1

    def fit(X: np.ndarray, y: np.ndarray):
        clf = make_pipeline(StandardScaler(), LogisticRegression(C=args.C, class_weight="balanced", max_iter=5000))
        return clf.fit(X, y)

    clf = fit(Xtr, ytr)
    fake_col = list(clf.classes_).index(1)
    report: dict = {}
    print("\nResults (threshold 0.5):")
    for name, rs in (("train", train), ("held-out", test)):
        if not rs:
            continue
        X, y = stack(rs)
        pw = clf.predict_proba(X)[:, fake_col]
        pf = np.array([clf.predict_proba(r["X"])[:, fake_col].mean() for r in rs])
        yf = np.array([r["y"] for r in rs])
        report[name] = {"window": metrics(y, pw), "file": metrics(yf, pf)}
        print(fmt_metrics(f"{name}/window", report[name]["window"]))
        print(fmt_metrics(f"{name}/file", report[name]["file"]))
    if not test:
        print("  ! no held-out data: train metrics only (optimistic). Add speakers or --holdout-speaker.")
    else:
        print("\nHeld-out files:")
        for r in test:
            p = clf.predict_proba(r["X"])[:, fake_col].mean()
            print(f"  {'FAKE' if r['y'] else 'real'}  P(fake)={p:.3f}  {r['speaker'] or '-':12} {r['file']}")

    if args.refit_all and test:
        Xall, yall = stack(rows, aug=args.phone_aug)
        clf = fit(Xall, yall)
        print("refit on train + held-out data")

    bundle = {
        "pipeline": clf, "wavlm_model": s.wavlm_model, "layer": args.layer,
        "window_s": args.window_s, "hop_s": args.hop_s, "threshold": 0.5,
        "meta": {"trained": datetime.now(timezone.utc).isoformat(timespec="seconds"), "csv": str(args.csv),
                 "n_files": len(rows), "n_windows_train": int(len(ytr)), "split": split_desc,
                 "phone_aug": args.phone_aug, "refit_all": bool(args.refit_all and test), "C": args.C,
                 "metrics": report},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, out_path)
    print(f"\nsaved {out_path}  (use SPOOF_PROVIDER=wavlm)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
