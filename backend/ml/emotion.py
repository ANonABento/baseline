"""Frozen WavLM-base-plus + logistic-regression emotion probe (V-owned). RESEARCH-ONLY, hackathon.

Trained on RAVDESS (acted speech, CC BY-NC-SA 4.0, non-shippable weights) by
scripts/train_emotion_probe.py -> data/models/emotion_probe.npz. Output is an estimate of
ACTED emotion category; on real spontaneous speech it is uncalibrated (calibration_status
not_established) and must be shown as such. Enabled with EMOTION_PROVIDER=wavlm; returns None when
disabled, the probe file is missing or inference fails, so the pipeline never depends on it."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)
PROBE = Path(__file__).resolve().parents[2] / "data" / "models" / "emotion_probe.npz"
_state: dict = {}


def enabled() -> bool:
    return os.environ.get("EMOTION_PROVIDER", "").lower() == "wavlm" and PROBE.exists()


def embed(model, audio: np.ndarray, layer: int) -> np.ndarray:
    import torch

    y = np.asarray(audio, dtype=np.float32)
    y = (y - y.mean()) / (y.std() + 1e-7)
    with torch.inference_mode():
        hs = model(torch.from_numpy(y)[None], output_hidden_states=True).hidden_states
    return hs[layer][0].mean(0).numpy()


def estimate(audio: np.ndarray, sample_rate: int = 16_000) -> dict | None:
    """{label: probability} for all classes (sums to 1), plus provenance; None if unavailable."""
    if not enabled() or sample_rate != 16_000 or len(audio) < 8_000:
        return None
    try:
        if not _state:
            from transformers import WavLMModel

            z = np.load(PROBE, allow_pickle=False)
            _state.update(z={k: z[k] for k in z.files}, model=WavLMModel.from_pretrained("microsoft/wavlm-base-plus").eval())
        z, model = _state["z"], _state["model"]
        x = (embed(model, audio, int(z["layer"])) - z["mean"]) / z["scale"]
        logits = z["coef"] @ x + z["intercept"]
        p = np.exp(logits - logits.max())
        p /= p.sum()
        return {"probs": {str(c): round(float(v), 3) for c, v in zip(z["classes"], p)},
                "model": "wavlm-base-plus frozen + logistic probe", "trained_on": "RAVDESS acted speech (24 actors)",
                "calibration_status": "not_established"}
    except Exception:  # noqa: BLE001 - never break the call pipeline
        log.warning("emotion probe failed", exc_info=True)
        return None
