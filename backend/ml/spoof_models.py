"""Spoof (synthetic speech) models. Use only via the `spoof` executor.

PretrainedSpoof  mo-thecreator/Deepfake-audio-detection (wav2vec2 classifier, labels
                 {0: fake, 1: real}); weights loaded from safetensors only.
WavLMEmbedder    frozen microsoft/wavlm-base-plus, mean-pooled hidden states per window.
                 Its main branch only has a pickle checkpoint, so we build the model from
                 config.json and load `model.safetensors` from the HF safetensors ref
                 (`wavlm_safetensors_revision`, default refs/pr/2), never the .bin.
SpoofLR          our logistic regression on WavLM embeddings (scripts/train_spoof.py).
                 Stored with joblib (= pickle): only load files you trained yourself.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ml import runtime

log = logging.getLogger(__name__)
EXECUTOR = "spoof"
SR = 16_000


class PretrainedSpoof:
    def __init__(self, repo: str, device: str = "auto"):
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

        self.repo = repo
        self.device = runtime.torch_device(device)
        self.fe = AutoFeatureExtractor.from_pretrained(repo)
        self.model = AutoModelForAudioClassification.from_pretrained(repo, use_safetensors=True).eval().to(self.device)
        labels = {int(k): str(v).lower() for k, v in self.model.config.id2label.items()}
        fake = [i for i, name in labels.items() if name in ("fake", "spoof", "synthetic", "deepfake")]
        if not fake:
            raise ValueError(f"{repo}: cannot find a fake/spoof label in {labels}")
        self.fake_idx = fake[0]

    @classmethod
    def get(cls, repo: str, device: str = "auto") -> "PretrainedSpoof":
        return runtime.cached(("spoof_pretrained", repo, device), lambda: cls(repo, device))

    def fake_probs(self, wins: list[np.ndarray]) -> np.ndarray:
        """P(fake) per window. Windows must have equal length (ml.audio.windows guarantees it)."""
        import torch

        if not wins:
            return np.zeros(0, dtype=np.float32)
        inp = self.fe([w.astype(np.float32, copy=False) for w in wins], sampling_rate=SR, return_tensors="pt", padding=True)
        inp = {k: v.to(self.device) for k, v in inp.items()}
        with torch.inference_mode():
            logits = self.model(**inp).logits.float()
        return logits.softmax(-1)[:, self.fake_idx].cpu().numpy()

    def warmup(self) -> None:
        # MPS compiles per input shape: warm the batch sizes a 3-15 s utterance produces.
        rng = np.random.default_rng(0)
        w = (0.05 * rng.standard_normal(SR * 4)).astype(np.float32)
        for n in (1, 2, 3):
            self.fake_probs([w] * n)
        runtime.sync_device(self.device)


class WavLMEmbedder:
    def __init__(self, repo: str = "microsoft/wavlm-base-plus", device: str = "auto",
                 safetensors_revision: str = "refs/pr/2"):
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        from transformers import AutoConfig, AutoFeatureExtractor, AutoModel

        self.repo = repo
        self.device = runtime.torch_device(device)
        self.fe = AutoFeatureExtractor.from_pretrained(repo)
        cfg = AutoConfig.from_pretrained(repo)
        model = AutoModel.from_config(cfg)
        try:  # repos that ship safetensors on main
            weights = hf_hub_download(repo, "model.safetensors")
        except Exception:
            weights = hf_hub_download(repo, "model.safetensors", revision=safetensors_revision)
        missing, unexpected = model.load_state_dict(load_file(weights), strict=False)
        if missing:
            raise RuntimeError(f"{repo}: safetensors is missing {len(missing)} weights, e.g. {missing[:3]}")
        if unexpected:
            log.warning("%s: %d unexpected weights ignored", repo, len(unexpected))
        self.model = model.eval().to(self.device)

    @classmethod
    def get(cls, repo: str, device: str = "auto", safetensors_revision: str = "refs/pr/2") -> "WavLMEmbedder":
        return runtime.cached(("wavlm", repo, device), lambda: cls(repo, device, safetensors_revision))

    def embed(self, wins: list[np.ndarray], layer: int = -1) -> np.ndarray:
        """(n_windows, hidden) mean-pooled embeddings. layer=-1 -> last hidden state,
        otherwise hidden_states[layer] (0 = CNN features after projection)."""
        import torch

        if not wins:
            return np.zeros((0, self.model.config.hidden_size), dtype=np.float32)
        inp = self.fe([w.astype(np.float32, copy=False) for w in wins], sampling_rate=SR, return_tensors="pt", padding=True)
        inp = {k: v.to(self.device) for k, v in inp.items() if k in ("input_values", "attention_mask")}
        with torch.inference_mode():
            out = self.model(**inp, output_hidden_states=layer != -1)
            h = out.last_hidden_state if layer == -1 else out.hidden_states[layer]
            e = h.mean(dim=1).float().cpu().numpy()
        return e

    def warmup(self) -> None:
        rng = np.random.default_rng(0)
        w = (0.05 * rng.standard_normal(SR * 3)).astype(np.float32)
        for n in (1, 2, 3):
            self.embed([w] * n)
        runtime.sync_device(self.device)


class SpoofLR:
    """Loads the dict saved by scripts/train_spoof.py."""

    def __init__(self, path: Path):
        import joblib

        if not path.is_file():
            raise FileNotFoundError(f"{path} not found; train it with scripts/train_spoof.py")
        bundle = joblib.load(path)  # pickle: only ever load our own trained file
        self.clf = bundle["pipeline"]
        self.wavlm_model: str = bundle.get("wavlm_model", "microsoft/wavlm-base-plus")
        self.layer: int = int(bundle.get("layer", -1))
        self.window_s: float = float(bundle.get("window_s", 3.0))
        self.hop_s: float = float(bundle.get("hop_s", self.window_s / 2))
        self.threshold: float = float(bundle.get("threshold", 0.5))
        self.meta: dict = bundle.get("meta", {})
        classes = list(self.clf.classes_)
        self.fake_col = classes.index(1)  # label 1 = fake / synthetic

    @classmethod
    def get(cls, path: Path) -> "SpoofLR":
        return runtime.cached(("spoof_lr", str(path)), lambda: cls(path))

    def fake_probs(self, emb: np.ndarray) -> np.ndarray:
        if len(emb) == 0:
            return np.zeros(0, dtype=np.float32)
        return self.clf.predict_proba(emb)[:, self.fake_col]
