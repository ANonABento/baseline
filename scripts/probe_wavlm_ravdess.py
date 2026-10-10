"""Frozen WavLM-base-plus probe vs the hand-built prosody features on RAVDESS (workplan 2.2).
EXPLORATORY. Acted emotion, 24 actors, actor-held-out GroupKFold(6), logistic regression on
mean-pooled hidden states of one layer (frozen encoder, no fine-tuning). Seed 0.
Licence: WavLM terms UNVERIFIED (docs/licences.md); research-only, hackathon.

  uv run --project backend --extra ml --with scikit-learn python scripts/probe_wavlm_ravdess.py
Writes results/probe_wavlm_ravdess.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
import public_checks as pc  # noqa: E402
from detectors import voice_state as vs  # noqa: E402
from ml.audio import read_audio  # noqa: E402

LAYERS = (3, 6, 9)


def main() -> None:
    import torch
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from transformers import WavLMModel

    torch.manual_seed(pc.SEED)
    model = WavLMModel.from_pretrained("microsoft/wavlm-base-plus").eval()
    files = sorted((pc.EXT / "ravdess" / "speech").rglob("*.wav"))
    actors, emo, X_by_layer = [], [], {l: [] for l in LAYERS}
    for p in files:
        parts = [int(x) for x in p.stem.split("-")]
        y = read_audio(p, 16_000)
        y = (y - y.mean()) / (y.std() + 1e-7)
        with torch.inference_mode():
            hs = model(torch.from_numpy(y)[None], output_hidden_states=True).hidden_states
        for l in LAYERS:
            X_by_layer[l].append(hs[l][0].mean(0).numpy())
        actors.append(parts[6])
        emo.append(pc.EMOTIONS[parts[2]])
    actors, emo = np.array(actors), np.array(emo)
    tasks = {"8-class emotion": emo, "high vs low arousal": np.array([e in pc.HIGH_AROUSAL for e in emo]).astype(str)}
    out = {"label": "EXPLORATORY", "n_clips": len(files), "n_actors": int(np.unique(actors).size), "model": "microsoft/wavlm-base-plus (frozen)", "tasks": {}}
    for tname, y in tasks.items():
        res = {"majority_baseline": round(float(max(np.mean(y == c) for c in np.unique(y))), 3)}
        for l in LAYERS:
            X = np.array(X_by_layer[l])
            pred = np.empty(len(y), dtype=object)
            for tr, te in GroupKFold(n_splits=6).split(X, y, actors):
                pred[te] = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)).fit(X[tr], y[tr]).predict(X[te])
            per_actor = np.array([np.mean(pred[actors == a] == y[actors == a]) for a in np.unique(actors)])
            res[f"wavlm_layer{l}"] = {"accuracy": round(float(np.mean(pred == y)), 3), "ci95_over_actors": pc.boot_ci(per_actor)}
        out["tasks"][tname] = res
    (ROOT / "results" / "probe_wavlm_ravdess.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out["tasks"], indent=1))


if __name__ == "__main__":
    main()
