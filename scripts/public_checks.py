"""Public-data checks for the voice-state signals (plan section 8, workplan 1.4). EXPLORATORY.

  A  AMI (spontaneous meetings): how often does the baseline-change rule fire on one speaker's
     ordinary talk? (no stress labels exist; this is a false-alarm-style rate, not accuracy)
  B  Read (LibriSpeech test-clean) vs spontaneous (AMI): do pause/rate/pitch-variation differ?
     CONFOUNDED by corpus, channel, speaker population; says nothing about reading per se.
  C  RAVDESS (acted emotion, 24 actors): (C1) emotion probe on handcrafted features with
     actor-held-out folds; (C2) does |z| vs the actor's own neutral baseline move for acted
     emotions? Acted emotion is not real stress.

Run (ephemeral extras, project pins untouched):
  uv run --project backend --extra ml --with pyarrow --with scikit-learn \\
      python scripts/public_checks.py [--quick]
Writes results/public_checks.json and results/public_checks.md. Seed 0. Needs data/external/
(scripts/fetch_open_data.py; LibriSpeech test-clean extracted)."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from detectors import voice_state as vs  # noqa: E402
from ml.audio import read_audio, resample  # noqa: E402

SEED = 0
EXT = ROOT / "data" / "external"
EMOTIONS = {1: "neutral", 2: "calm", 3: "happy", 4: "sad", 5: "angry", 6: "fearful", 7: "disgust", 8: "surprised"}
HIGH_AROUSAL = {"happy", "angry", "fearful", "surprised"}


def boot_ci(values: np.ndarray, n: int = 2000) -> list[float]:
    """95% percentile bootstrap CI of the mean, resampling the unit (speaker/actor), seed fixed."""
    rng = np.random.default_rng(SEED)
    v = np.asarray(values, dtype=float)
    m = [rng.choice(v, v.size).mean() for _ in range(n)]
    return [round(float(np.percentile(m, 2.5)), 3), round(float(np.percentile(m, 97.5)), 3)]


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    sp = np.sqrt(((a.size - 1) * a.var(ddof=1) + (b.size - 1) * b.var(ddof=1)) / (a.size + b.size - 2))
    return float((a.mean() - b.mean()) / sp)


# ---------- AMI ----------
def ami_utterances(max_speakers: int, min_utts: int = 15):
    """Yield (meeting, speaker, [features...]) with adjacent same-speaker segments merged
    (gap < 0.5 s, up to 10 s) so utterances are long enough for the quality gate."""
    import pyarrow.parquet as pq
    import soundfile as sf

    by_spk: dict[tuple[str, str], list[tuple[float, float, np.ndarray]]] = {}
    for shard in sorted((EXT / "ami" / "ihm").glob("*.parquet")):
        pf = pq.ParquetFile(shard)
        for batch in pf.iter_batches(batch_size=64, columns=["audio", "meeting_id", "speaker_id", "begin_time", "end_time"]):
            for r in batch.to_pylist():
                a, sr = sf.read(io.BytesIO(r["audio"]["bytes"]), dtype="float32")
                a = resample(a if a.ndim == 1 else a.mean(1), sr, vs.SAMPLE_RATE)
                by_spk.setdefault((r["meeting_id"], r["speaker_id"]), []).append((r["begin_time"], r["end_time"], a))
    out = []
    for (mtg, spk), segs in sorted(by_spk.items()):
        segs.sort(key=lambda s: s[0])
        merged, cur, t_end = [], [], None
        for b, e, a in segs:
            if cur and (b - t_end > 0.5 or sum(x.size for x in cur) / vs.SAMPLE_RATE > 10):
                merged.append(np.concatenate(cur))
                cur = []
            cur.append(a)
            t_end = e
        if cur:
            merged.append(np.concatenate(cur))
        feats = [vs.extract_features(m, vs.SAMPLE_RATE) for m in merged]
        if sum(f is not None for f in feats) >= min_utts:
            out.append((mtg, spk, merged, feats))
    rng = np.random.default_rng(SEED)
    rng.shuffle(out)
    return out[:max_speakers]


def check_a_b(quick: bool) -> tuple[dict, dict]:
    spk = ami_utterances(8 if quick else 30)
    per_spk, ami_pool = [], {k: [] for k in ("pause_frac", "rate_proxy", "f0_std_st")}
    for mtg, sid, _, feats in spk:
        base, n_ok, n_post, n_fire, n_change = vs.SpeakerBaseline(), 0, 0, 0, 0
        for f in feats:
            problems = vs.quality_problems(f)
            if problems:
                continue
            n_ok += 1
            d = vs.assess(f, base)
            if d["status"] == "ok":
                n_post += 1
                n_fire += any(abs(z) >= vs.Z_FIRE for z in d["z"].values())
                n_change += d["stress_related_change"] > 0
        usable = [f for f in feats if not vs.quality_problems(f)]
        for k in ami_pool:
            ami_pool[k].append(float(np.mean([f[k] for f in usable])))
        per_spk.append({"meeting": mtg, "speaker": sid, "n_utts": len(feats), "n_usable": n_ok,
                        "any_feature_fired_rate": round(n_fire / n_post, 3) if n_post else None,
                        "sustained_change_rate": round(n_change / n_post, 3) if n_post else None})
    rates = np.array([s["sustained_change_rate"] for s in per_spk if s["sustained_change_rate"] is not None])
    anyr = np.array([s["any_feature_fired_rate"] for s in per_spk if s["any_feature_fired_rate"] is not None])
    a = {"n_speakers": len(per_spk), "usable_utterance_share": round(sum(s["n_usable"] for s in per_spk) / sum(s["n_utts"] for s in per_spk), 3),
         "any_feature_fired_rate_mean": round(float(anyr.mean()), 3), "any_feature_fired_ci95_over_speakers": boot_ci(anyr),
         "sustained_change_rate_mean": round(float(rates.mean()), 3), "sustained_change_ci95_over_speakers": boot_ci(rates),
         "per_speaker": per_spk}

    # B: LibriSpeech (crop to <= 10 s, 4 utterances per speaker) vs AMI speaker means
    rng = np.random.default_rng(SEED)
    ls_pool = {k: [] for k in ami_pool}
    spk_dirs = sorted((EXT / "LibriSpeech" / "test-clean").iterdir())
    for sd in spk_dirs[: (10 if quick else len(spk_dirs))]:
        files = sorted(sd.rglob("*.flac"))
        rows = []
        for p in [files[i] for i in rng.permutation(len(files))[:4]]:
            f = vs.extract_features(read_audio(p, vs.SAMPLE_RATE)[: 10 * vs.SAMPLE_RATE], vs.SAMPLE_RATE)
            if not vs.quality_problems(f):
                rows.append(f)
        if rows:
            for k in ls_pool:
                ls_pool[k].append(float(np.mean([r[k] for r in rows])))
    b = {"n_librispeech_speakers": len(ls_pool["pause_frac"]), "n_ami_speakers": len(ami_pool["pause_frac"]), "features": {}}
    for k in ami_pool:
        la, aa = np.array(ls_pool[k]), np.array(ami_pool[k])
        b["features"][k] = {"librispeech_mean": round(float(la.mean()), 3), "ami_mean": round(float(aa.mean()), 3),
                            "cohens_d_ami_minus_ls": round(cohens_d(aa, la), 2)}
    return a, b


# ---------- RAVDESS ----------
def ravdess_table(quick: bool):
    import librosa

    rows = []
    files = sorted((EXT / "ravdess" / "speech").rglob("*.wav"))
    if quick:
        files = [f for f in files if int(f.parent.name.split("_")[1]) <= 8]
    for p in files:
        parts = [int(x) for x in p.stem.split("-")]
        emo, intensity, actor = EMOTIONS[parts[2]], parts[3], parts[6]
        y = read_audio(p, vs.SAMPLE_RATE)
        y, _ = librosa.effects.trim(y, top_db=30)
        f = vs.extract_features(y, vs.SAMPLE_RATE)
        if f is None or np.isnan(f.get("f0_median_st", np.nan)):
            continue
        mf = librosa.feature.mfcc(y=y, sr=vs.SAMPLE_RATE, n_mfcc=13)
        rows.append({"actor": actor, "emotion": emo, "intensity": intensity, "f": f,
                     "mfcc": np.concatenate([mf.mean(1), mf.std(1)])})
    return rows


def check_c(quick: bool) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    rows = ravdess_table(quick)
    actors = np.array([r["actor"] for r in rows])
    emo = np.array([r["emotion"] for r in rows])
    X_pros = np.array([[r["f"][k] for k in vs.FEATURES] for r in rows])
    X_all = np.hstack([X_pros, np.array([r["mfcc"] for r in rows])])
    # actor-normalised copies: subtract each actor's mean (uses unlabelled data only)
    def actor_norm(X):
        Xn = X.copy()
        for a in np.unique(actors):
            Xn[actors == a] -= X[actors == a].mean(0)
        return Xn

    out = {"n_clips": len(rows), "n_actors": int(np.unique(actors).size), "tasks": {}}
    folds = min(6, np.unique(actors).size)
    tasks = {"8-class emotion": emo, "high vs low arousal": np.array([e in HIGH_AROUSAL for e in emo]).astype(str)}
    for tname, y in tasks.items():
        chance = float(max(np.mean(y == c) for c in np.unique(y)))
        res = {"majority_baseline": round(chance, 3)}
        for fname, X in (("prosody5", X_pros), ("prosody5_actor_norm", actor_norm(X_pros)), ("prosody5+mfcc26", X_all)):
            clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
            pred = np.empty(len(y), dtype=object)
            for tr, te in GroupKFold(n_splits=folds).split(X, y, actors):
                pred[te] = clf.fit(X[tr], y[tr]).predict(X[te])
            per_actor = np.array([np.mean(pred[actors == a] == y[actors == a]) for a in np.unique(actors)])
            res[fname] = {"accuracy": round(float(np.mean(pred == y)), 3), "ci95_over_actors": boot_ci(per_actor)}
        out["tasks"][tname] = res

    # C2: |z| vs the actor's own neutral baseline (normal-intensity neutral clips, first 3),
    # per emotion share of clips where any feature has |z| >= 2 (single clip, not sustained)
    share = {e: [] for e in EMOTIONS.values()}
    direction = {e: {k: [] for k in vs.FEATURES} for e in EMOTIONS.values()}
    for a in np.unique(actors):
        mine = [r for r in rows if r["actor"] == a]
        neutral = [r for r in mine if r["emotion"] == "neutral" and r["intensity"] == 1]
        if len(neutral) < 4:
            continue
        base = vs.SpeakerBaseline()
        for r in neutral[:3]:
            base.add(r["f"])
        for e in EMOTIONS.values():
            zs = [base.zscores(r["f"]) for r in mine if r["emotion"] == e and not (r["emotion"] == "neutral" and r in neutral[:3])]
            if zs:
                share[e].append(np.mean([any(abs(v) >= vs.Z_FIRE for v in z.values()) for z in zs]))
                for k in vs.FEATURES:
                    direction[e][k].append(float(np.mean([z[k] for z in zs])))
    out["c2_share_clips_with_any_feature_abs_z_at_Z_FIRE"] = {e: {"mean": round(float(np.mean(v)), 3), "ci95_over_actors": boot_ci(np.array(v)), "n_actors": len(v)} for e, v in share.items() if v}
    out["c2_mean_signed_z"] = {e: {k: round(float(np.mean(v)), 2) for k, v in d.items() if v} for e, d in direction.items() if share[e]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    a, b = check_a_b(args.quick)
    c = check_c(args.quick)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout.strip())
    import librosa
    import sklearn

    res = {"label": "EXPLORATORY", "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_sha": sha + ("-dirty" if dirty else ""),
           "seed": SEED, "quick": args.quick, "versions": {"numpy": np.__version__, "librosa": librosa.__version__, "scikit-learn": sklearn.__version__},
           "command": "python scripts/public_checks.py" + (" --quick" if args.quick else ""),
           "data_manifests": {n: json.loads((EXT / n / "MANIFEST.json").read_text()) for n in ("ami", "ravdess") if (EXT / n / "MANIFEST.json").exists()},
           "A_ami_baseline_rule": a, "B_read_vs_spontaneous": b, "C_ravdess": c}
    out = ROOT / "results" / ("public_checks_quick.json" if args.quick else "public_checks.json")
    out.write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if k.startswith(("A_", "B_", "C_"))}, indent=1, default=str)[:6000])
    print("wrote", out)


if __name__ == "__main__":
    main()
