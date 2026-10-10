"""Enrolled voiceprint store: data/enroll/<customer_id>.npy (L2-normalised mean ECAPA
embedding) + <customer_id>.json (metadata). Numpy only, so the API works without torch."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def valid_customer_id(customer_id: str) -> bool:
    return bool(_ID.match(customer_id or "")) and ".." not in customer_id


@dataclass
class Voiceprint:
    customer_id: str
    embedding: np.ndarray
    meta: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return str(self.meta.get("name") or "")


def paths(enroll_dir: Path, customer_id: str) -> tuple[Path, Path]:
    if not valid_customer_id(customer_id):
        raise ValueError(f"invalid customer id: {customer_id!r}")
    return enroll_dir / f"{customer_id}.npy", enroll_dir / f"{customer_id}.json"


def save(enroll_dir: Path, customer_id: str, embedding: np.ndarray, meta: dict) -> Path:
    npy, js = paths(enroll_dir, customer_id)
    enroll_dir.mkdir(parents=True, exist_ok=True)
    e = embedding.astype(np.float32)
    np.save(npy, e / max(float(np.linalg.norm(e)), 1e-9), allow_pickle=False)
    js.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return npy


def load(enroll_dir: Path, customer_id: str) -> Voiceprint | None:
    try:
        npy, js = paths(enroll_dir, customer_id)
    except ValueError:
        return None
    if not npy.is_file():
        return None
    emb = np.load(npy, allow_pickle=False).astype(np.float32).reshape(-1)
    meta = {}
    if js.is_file():
        try:
            meta = json.loads(js.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    return Voiceprint(customer_id, emb, meta)


def list_enrolled(enroll_dir: Path) -> list[dict]:
    out = []
    if enroll_dir.is_dir():
        for npy in sorted(enroll_dir.glob("*.npy")):
            vp = load(enroll_dir, npy.stem)
            if vp is not None:
                out.append({"id": vp.customer_id, "name": vp.name, "n_segments": vp.meta.get("n_segments"),
                            "audio_s": vp.meta.get("audio_s"), "model": vp.meta.get("model"),
                            "created": vp.meta.get("created")})
    return out
