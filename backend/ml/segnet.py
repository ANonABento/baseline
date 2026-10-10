"""Fine-tuned Stage A signal model, inference only (trained in notebooks/baseline_brief_architecture.ipynb).

WavLM-base-plus (top 4 layers fine-tuned) + DeBERTa-v3-base (top 2) + attentive pooling, learnable layer mixer,
acoustic scalars and a fusion layer; heads for emotion (8 classes) and arousal (2). Weights:
data/models/baseline_brief_full.pt (Git LFS; run `git lfs pull`). Enabled with SEGNET_PROVIDER=brief; returns None
when disabled, the weights are missing/an LFS pointer, or inference fails, so the call pipeline never depends on it.

Held-out test (results/brief_architecture_full.json, exploratory, mixed corpora): emotion accuracy 0.623, arousal
0.798 (fused). The delivery head is NOT used (known bug: scores 0.0), and Stage B (bluff/fabrication/mismatch) is not
wired. Outputs are model scores: calibration_status not_established, and trained mostly on acted or meeting speech.
Runs on CPU: DeBERTa hits an Apple-GPU matmul assertion on MPS (notebook note)."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)
PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "baseline_brief_full.pt"
SR = 16_000
MAX_AUDIO_S = 6.0
MAX_TOK = 64
N_SCALAR = 7
D = 256
_state: dict = {}
_lock = threading.Lock()


def enabled() -> bool:
    on = os.environ.get("SEGNET_PROVIDER", "").lower() in ("brief", "1", "on", "true")
    return on and PATH.exists() and PATH.stat().st_size > 1_000_000  # an LFS pointer is ~130 bytes


def scalar_feats(y: np.ndarray) -> np.ndarray:
    """Same 7 acoustic scalars as the notebook (duration, active loudness, peak, clipping, pause fraction, ZCR, loudness range)."""
    import librosa

    fr = librosa.util.frame(y, frame_length=400, hop_length=160) if len(y) >= 400 else np.zeros((400, 1), dtype=np.float32)
    db = 20 * np.log10(np.sqrt((fr ** 2).mean(0) + 1e-12) + 1e-6)
    act = db > max(np.percentile(db, 10) + 10, np.percentile(db, 95) - 25)
    return np.array([len(y) / SR, db[act].mean() if act.any() else db.mean(), np.abs(y).max(), np.mean(np.abs(y) >= 0.99),
                     1 - act.mean(), np.mean(np.abs(np.diff(np.signbit(y).astype(np.int8)))) if len(y) > 1 else 0,
                     np.percentile(db, 95) - np.percentile(db, 10)], dtype=np.float32)


def _build(tasks: dict, audio_ckpt: str, text_ckpt: str):
    import torch
    from torch import nn
    from transformers import AutoModel

    def load_fp32(name):
        try:
            return AutoModel.from_pretrained(name, dtype=torch.float32)
        except TypeError:
            return AutoModel.from_pretrained(name, torch_dtype=torch.float32)

    class SegNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.audio, self.text = load_fp32(audio_ckpt), load_fp32(text_ckpt)
            if hasattr(self.audio.config, "layerdrop"):
                self.audio.config.layerdrop = 0.0  # random layer skipping would break the layer mixer
            Ha, Ht = self.audio.config.hidden_size, self.text.config.hidden_size
            self.lw = nn.Parameter(torch.zeros(self.audio.config.num_hidden_layers + 1))
            self.att = nn.Linear(Ha, 1)
            self.a = nn.Sequential(nn.LayerNorm(Ha), nn.Linear(Ha, D), nn.GELU(), nn.Dropout(0.2))
            self.t = nn.Sequential(nn.LayerNorm(Ht), nn.Linear(Ht, D), nn.GELU(), nn.Dropout(0.2))
            self.s = nn.Sequential(nn.LayerNorm(N_SCALAR), nn.Linear(N_SCALAR, 32), nn.GELU())
            self.fuse = nn.Sequential(nn.Linear(2 * D + 32 + 2, D), nn.GELU(), nn.Dropout(0.3))
            self.heads = nn.ModuleDict({t: nn.Linear(D, len(c)) for t, c in tasks.items()})

        def forward(self, wav, sc, ids, ma, mt):
            hs = torch.stack(self.audio(wav, output_hidden_states=True).hidden_states)
            h = (hs * torch.softmax(self.lw, 0)[:, None, None, None]).sum(0)
            w = self.att(h).squeeze(-1).softmax(1)  # one utterance per batch: no padding mask needed
            za = self.a((h * w.unsqueeze(-1)).sum(1)) * ma
            ht = self.text(input_ids=ids, attention_mask=torch.ones_like(ids)).last_hidden_state.mean(1)
            zt = self.t(ht) * mt
            z = self.fuse(torch.cat([za, zt, self.s(sc) * ma, ma, mt], 1))
            return {t: head(z) for t, head in self.heads.items()}

    return SegNet()


def load() -> bool:
    """Build the network and load the fine-tuned weights once (thread-safe). False if unavailable."""
    if _state.get("ready"):
        return True
    if not enabled():
        return False
    with _lock:
        if _state.get("ready"):
            return True
        try:
            import sentencepiece as spm
            import torch
            from huggingface_hub import hf_hub_download

            ck = torch.load(PATH, map_location="cpu", weights_only=False)
            net = _build(ck["tasks"], ck["audio_ckpt"], ck["text_ckpt"]).eval()
            res = net.load_state_dict(ck["trainable"], strict=False)
            if res.unexpected_keys:
                raise RuntimeError(f"unexpected checkpoint keys: {res.unexpected_keys[:3]}")
            spm_path = hf_hub_download(ck["text_ckpt"], "spm.model")  # the HF auto-tokenizer path needs protobuf; spm is enough
            _state.update(net=net, tasks=ck["tasks"], sp=spm.SentencePieceProcessor(model_file=spm_path), ready=True)
            log.info("segnet loaded: %s (%d fine-tuned tensors)", PATH.name, len(ck["trainable"]))
        except Exception:  # noqa: BLE001 - never break the call pipeline
            log.warning("segnet unavailable", exc_info=True)
            _state["ready"] = False
            return False
    return True


def estimate(audio: np.ndarray, sample_rate: int = SR, text: str = "") -> dict | None:
    """Emotion and arousal probabilities for one utterance. Uses the text branch when `text` is given (fused), else audio only."""
    if sample_rate != SR or len(audio) < 8_000 or not load():
        return None
    try:
        import torch

        y = np.asarray(audio, dtype=np.float32)[: int(MAX_AUDIO_S * SR)]
        sc = torch.from_numpy(scalar_feats(y))[None]
        wav = torch.from_numpy((y - y.mean()) / (y.std() + 1e-7))[None]  # normalised for the encoder only, as in training
        sp = _state["sp"]
        text = (text or "").strip()
        ids = torch.tensor([[1] + sp.encode(text)[: MAX_TOK - 2] + [2]])  # [CLS] ... [SEP]
        ma, mt = torch.ones(1, 1), torch.full((1, 1), 1.0 if text else 0.0)
        with torch.inference_mode():
            lg = _state["net"](wav, sc, ids, ma, mt)
        out = {t: {c: round(float(p), 3) for c, p in zip(_state["tasks"][t], lg[t][0].softmax(-1))} for t in ("emotion", "arousal")}
        return {**out, "mode": "fused" if text else "audio_only", "model": "WavLM-base-plus + DeBERTa-v3-base, fine-tuned (baseline_brief_full)",
                "held_out_accuracy": {"emotion": 0.623, "arousal": 0.798, "source": "results/brief_architecture_full.json, exploratory"},
                "calibration_status": "not_established"}
    except Exception:  # noqa: BLE001
        log.warning("segnet inference failed", exc_info=True)
        return None
