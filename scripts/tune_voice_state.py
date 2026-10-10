"""Threshold sweep for voice_state (workplan 2.1). EXPLORATORY tuning, not validation.

Declared BEFORE running (2026-10-10): grid Z_FIRE {2,2.5,3,4} x baseline size {3,5,8} x
MIN_FEATS {1,2} x SUSTAIN_N {2,3}. Selection rule on the TUNE half only (AMI speakers with even
index; RAVDESS actors 1-12): among settings with mean AMI sustained-change rate <= 0.15, pick the
one maximising (RAVDESS high-arousal flag share - RAVDESS held-out neutral/calm flag share); ties
-> larger Z_FIRE, then larger baseline. The chosen setting is then reported on the REPORT half
(odd AMI speakers; RAVDESS actors 13-24). Both halves are small and from the same corpora, so the
report-half numbers are still optimistic about unseen speakers and channels.

DEVIATION (same day, after the first run): the first run picked baseline size 8, which uses every
RAVDESS neutral/calm clip so the held-out calm false-alarm rate was null and was counted as 0.
Rule amended: settings with no measurable held-out calm rate are ineligible. First-run output is
not kept; only the amended run is in results/.
DEVIATION 2 (after the person-level re-split): the declared tie-break did not cover SUSTAIN_N and
RAVDESS single-clip scores ignore it, so ties were resolved by grid order. Tie-break extended:
then larger SUSTAIN_N (fewer false alarms). Earlier outputs are overwritten.

  uv run --project backend --extra ml --with pyarrow --with scikit-learn python scripts/tune_voice_state.py
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
import public_checks as pc  # noqa: E402
from detectors import voice_state as vs  # noqa: E402

HIGH = {"happy", "angry", "fearful", "surprised"}


def setting_apply(z, n, m, s):
    vs.Z_FIRE, vs.MIN_BASELINE_UTTS, vs.MIN_FEATS, vs.SUSTAIN_N = z, n, m, s


def ami_rate(speakers, n):
    rates = []
    for _, _, _, feats in speakers:
        base, post, ch = vs.SpeakerBaseline(min_n=n), 0, 0
        for f in feats:
            if vs.quality_problems(f):
                continue
            d = vs.assess(f, base)
            if d["status"] == "ok":
                post += 1
                ch += d["stress_related_change"] > 0
        if post:
            rates.append(ch / post)
    return float(np.mean(rates)), rates


def ravdess_rates(rows, actors, n):
    hi, calm = [], []
    for a in actors:
        mine = [r for r in rows if r["actor"] == a]
        pool = [r for r in mine if (r["emotion"] == "neutral") or (r["emotion"] == "calm" and r["intensity"] == 1)]
        pool.sort(key=lambda r: (r["emotion"] != "neutral",))  # neutral first
        if len(pool) < n:
            continue
        base = vs.SpeakerBaseline(min_n=n)
        for r in pool[:n]:
            base.add(r["f"])
        def fires(r):
            z = base.zscores(r["f"])
            return len([v for v in z.values() if abs(v) >= vs.Z_FIRE]) >= vs.MIN_FEATS
        h = [fires(r) for r in mine if r["emotion"] in HIGH]
        c = [fires(r) for r in pool[n:]]
        hi.append(np.mean(h))
        if c:
            calm.append(np.mean(c))
    return float(np.mean(hi)), (float(np.mean(calm)) if calm else None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("person", "meeting"), default="person",
                    help="meeting = robustness check: halves share no meeting (and therefore no room/channel/topic)")
    args = ap.parse_args()
    ami = pc.ami_utterances(30)
    rows = pc.ravdess_table(False)
    key = 1 if args.split == "person" else 0  # tuple = (meeting, speaker, audio, feats)
    spk_ids = sorted({x[key] for x in ami})  # person split: no speaker in both halves; meeting split: no meeting in both
    tune_ids = set(spk_ids[0::2])
    tune_ami = [x for x in ami if x[key] in tune_ids]
    rep_ami = [x for x in ami if x[key] not in tune_ids]
    if args.split == "meeting":  # people may repeat across meetings; report how many are in both halves
        print("speaker ids in both halves:", len({x[1] for x in tune_ami} & {x[1] for x in rep_ami}))
    tune_act, rep_act = list(range(1, 13)), list(range(13, 25))
    grid = []
    for z, n, m, s in itertools.product((2.0, 2.5, 3.0, 4.0), (3, 5, 8), (1, 2), (2, 3)):
        setting_apply(z, n, m, s)
        a, _ = ami_rate(tune_ami, n)
        hi, calm = ravdess_rates(rows, tune_act, n)
        grid.append({"z_fire": z, "baseline_n": n, "min_feats": m, "sustain_n": s, "ami_sustained_rate": round(a, 3),
                     "ravdess_high_flag": round(hi, 3), "ravdess_calm_flag": None if calm is None else round(calm, 3)})
    ok = [g for g in grid if g["ami_sustained_rate"] <= 0.15 and g["ravdess_calm_flag"] is not None]
    best = max(ok, key=lambda g: (g["ravdess_high_flag"] - g["ravdess_calm_flag"], g["z_fire"], g["baseline_n"], g["sustain_n"])) if ok else None
    report = None
    if best:
        setting_apply(best["z_fire"], best["baseline_n"], best["min_feats"], best["sustain_n"])
        a, rates = ami_rate(rep_ami, best["baseline_n"])
        hi, calm = ravdess_rates(rows, rep_act, best["baseline_n"])
        report = {"ami_sustained_rate": round(a, 3), "ami_ci95_over_speakers": pc.boot_ci(np.array(rates)), "n_ami_speakers": len(rates),
                  "ravdess_high_flag": round(hi, 3), "ravdess_calm_flag": None if calm is None else round(calm, 3), "n_actors": len(rep_act)}
    out = {"label": "EXPLORATORY tuning", "seed": pc.SEED, "selection_rule": "see script docstring (incl. DEVIATION note)",
           "n_settings": len(grid), "grid_tune_half": grid, "chosen": best, "report_half": report}
    import subprocess
    out["git_sha"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip() + "-dirty?"
    out["command"] = "python scripts/tune_voice_state.py"
    out["data_manifests"] = {n: json.loads((pc.EXT / n / "MANIFEST.json").read_text()) for n in ("ami", "ravdess")}
    out["split"] = args.split
    out["n_ami_speaker_ids"] = {"tune": len(tune_ids), "report": len(spk_ids) - len(tune_ids)}
    (ROOT / "results" / ("tune_voice_state.json" if args.split == "person" else "tune_voice_state_meeting_split.json")).write_text(json.dumps(out, indent=1))
    print(json.dumps({"chosen": best, "report_half": report, "n_ok_settings": len(ok)}, indent=1))


if __name__ == "__main__":
    main()
