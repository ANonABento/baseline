"""Train the frozen-WavLM emotion probe on ALL 24 RAVDESS actors and save data/models/emotion_probe.npz.
Layer 6 (best in results/probe_wavlm_ravdess.json; chosen on the same folds). RESEARCH-ONLY weights
(RAVDESS CC BY-NC-SA 4.0): see docs/licences.md. Held-out accuracy comes from probe_wavlm_ravdess.py, not here.

  uv run --project backend --extra ml --with scikit-learn python scripts/train_emotion_probe.py"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
import public_checks as pc  # noqa: E402
from ml import emotion  # noqa: E402
from ml.audio import read_audio  # noqa: E402

LAYER = 6


def main() -> None:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from transformers import WavLMModel

    model = WavLMModel.from_pretrained("microsoft/wavlm-base-plus").eval()
    X, y = [], []
    for p in sorted((pc.EXT / "ravdess" / "speech").rglob("*.wav")):
        parts = [int(x) for x in p.stem.split("-")]
        X.append(emotion.embed(model, read_audio(p, 16_000), LAYER))
        y.append(pc.EMOTIONS[parts[2]])
    X, y = np.array(X), np.array(y)
    sc = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=3000).fit(sc.transform(X), y)
    emotion.PROBE.parent.mkdir(parents=True, exist_ok=True)
    np.savez(emotion.PROBE, coef=clf.coef_, intercept=clf.intercept_, mean=sc.mean_, scale=sc.scale_,
             classes=clf.classes_, layer=np.array(LAYER))
    print("saved", emotion.PROBE, "classes", list(clf.classes_), "n", len(y))


if __name__ == "__main__":
    main()
