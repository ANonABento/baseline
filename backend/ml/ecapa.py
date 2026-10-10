"""SpeechBrain ECAPA-TDNN speaker embeddings (CPU). Use only via the `speaker` executor.

Audio is passed as tensors to `encode_batch` (never a path): torchaudio.load is broken in
this torch build without torchcodec."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ml import runtime
from ml.audio import windows

log = logging.getLogger(__name__)
EXECUTOR = "speaker"
SR = 16_000


class EcapaEncoder:
    def __init__(self, repo: str, savedir: Path, device: str = "cpu"):
        from speechbrain.inference.speaker import EncoderClassifier

        self.repo = repo
        self.device = device
        savedir.mkdir(parents=True, exist_ok=True)
        self.model = EncoderClassifier.from_hparams(source=repo, savedir=str(savedir), run_opts={"device": device})
        self.model.eval()

    @classmethod
    def get(cls, repo: str, pretrained_dir: Path, device: str = "cpu") -> "EcapaEncoder":
        savedir = pretrained_dir / repo.replace("/", "--")
        return runtime.cached(("ecapa", repo, device), lambda: cls(repo, savedir, device))

    def embed(self, audio: np.ndarray) -> np.ndarray:
        """L2-normalised 192-d embedding for one mono 16 kHz float32 clip."""
        import torch

        with torch.inference_mode():
            x = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))[None].to(self.device)
            e = self.model.encode_batch(x).squeeze().float().cpu().numpy()
        return e / max(float(np.linalg.norm(e)), 1e-9)

    def embed_long(self, audio: np.ndarray, win_s: float = 4.0, min_s: float = 1.5) -> list[np.ndarray]:
        """Utterance-sized chunks (for enrollment), so the profile matches per-utterance tests."""
        return [self.embed(w) for w in windows(audio, SR, win_s, win_s, min_s=min_s)]

    def warmup(self) -> None:
        rng = np.random.default_rng(0)
        self.embed((0.05 * rng.standard_normal(SR * 2)).astype(np.float32))


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / max(float(np.linalg.norm(a) * np.linalg.norm(b)), 1e-9))
