"""Voice-state signal summary relative to the speaker's OWN earlier delivery (V-owned).

This is NOT lie detection and produces no honesty/deception output. It measures how this
utterance's pitch, loudness, speaking-rate proxy and pauses differ from the same speaker's
earlier utterances, and reports a hedged "change vs own baseline". Such changes can have
many causes (excitement, a noisy line, a new topic, the microphone). Calibration against
real stress is NOT established: no open dataset has stress ground truth (HYPOTHESIS, see
docs/finetuning_plan.md section 2).

Pure functions + a small baseline class, so the z-score step is unit-testable without audio
models. `ProsodyDetector` (prosody.py) wires this into the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SAMPLE_RATE = 16_000
FRAME_S = 0.025
HOP_S = 0.010

# Minimum evidence before any statement is made.
MIN_DURATION_S = 1.0
MAX_CLIPPED_FRAC = 0.01  # share of samples at |x| >= 0.99
MIN_SNR_DB = 10.0
MIN_VOICED_FRAC = 0.15
MIN_BASELINE_UTTS = 3

# Features compared with the baseline, and the smallest spread we trust (units in comments).
FEATURES = ("f0_median_st", "f0_std_st", "rms_db", "rate_proxy", "pause_frac")
Z_FLOORS = {
    "f0_median_st": 1.0,  # semitones
    "f0_std_st": 0.5,  # semitones
    "rms_db": 2.0,  # dB
    "rate_proxy": 0.5,  # energy peaks per second
    "pause_frac": 0.05,  # fraction of frames
}
Z_FIRE = 2.5  # |z| on a feature to count as a change (tuned, see results/tune_voice_state.json)
SUSTAIN_N = 3  # consecutive qualifying utterances before reporting a change
MIN_FEATS = 2  # features that must exceed Z_FIRE together in one utterance


def _frames(audio: np.ndarray, sr: int) -> np.ndarray:
    n, hop = int(FRAME_S * sr), int(HOP_S * sr)
    if len(audio) < n:
        return np.zeros((0, n), dtype=np.float32)
    idx = np.arange(0, len(audio) - n + 1, hop)[:, None] + np.arange(n)[None, :]
    return audio[idx]


def extract_features(audio: np.ndarray, sr: int = SAMPLE_RATE) -> dict[str, float] | None:
    """Per-utterance features, or None when the audio is too short to frame. Units: st =
    semitones re 1 Hz, dB = dBFS (relative, uncalibrated mic), rate_proxy = energy peaks/s
    (a rough syllable-rate proxy, not words per minute)."""
    audio = np.asarray(audio, dtype=np.float32)
    if audio.size < int(FRAME_S * sr) * 2 or not np.all(np.isfinite(audio)):
        return None  # too short, or NaN/inf (never reaches librosa)
    frames = _frames(audio, sr)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    db = 20.0 * np.log10(np.maximum(rms, 1e-6))
    floor = float(np.percentile(db, 10))
    peak = float(np.percentile(db, 95))
    active = db > max(floor + 10.0, peak - 25.0)  # voiced-or-loud frames
    out: dict[str, float] = {
        "duration_s": audio.size / sr,
        "rms_db": float(db[active].mean()) if active.any() else float(db.mean()),
        "snr_db": peak - floor,
        "clipped_frac": float(np.mean(np.abs(audio) >= 0.99)),
        "pause_frac": float(1.0 - active.mean()),
    }
    # energy peaks (smoothed envelope), a syllable-rate proxy
    env = np.convolve(db, np.ones(5) / 5.0, mode="same")
    thr = floor + 0.5 * max(peak - floor, 1.0)
    peaks = (env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & (env[1:-1] > thr)
    out["rate_proxy"] = float(peaks.sum() / (audio.size / sr))
    out.update(_pitch_features(audio, sr))
    return out


def _pitch_features(audio: np.ndarray, sr: int) -> dict[str, float]:
    import librosa

    f0 = librosa.yin(audio, fmin=65.0, fmax=400.0, sr=sr, frame_length=1024, hop_length=int(HOP_S * sr))
    n = min(len(f0), len(_frames(audio, sr)))
    f0 = f0[:n]
    rms = librosa.feature.rms(y=audio, frame_length=1024, hop_length=int(HOP_S * sr))[0][:n]
    voiced = (rms > 0.5 * np.median(rms[rms > 0])) if np.any(rms > 0) else np.zeros(n, bool)
    voiced &= (f0 > 66.0) & (f0 < 399.0)  # yin pins to the search limits on unvoiced frames
    if voiced.sum() < 5:
        return {"voiced_frac": float(voiced.mean()) if n else 0.0, "f0_median_st": float("nan"), "f0_std_st": float("nan")}
    st = 12.0 * np.log2(f0[voiced])
    return {"voiced_frac": float(voiced.mean()), "f0_median_st": float(np.median(st)), "f0_std_st": float(np.std(st))}


def quality_problems(f: dict[str, float] | None) -> list[str]:
    """Reasons this utterance cannot support any statement (empty = usable)."""
    if f is None:
        return ["too short or invalid audio"]
    p = []
    if f["duration_s"] < MIN_DURATION_S:
        p.append(f"under {MIN_DURATION_S:.0f} s of speech")
    if f["clipped_frac"] > MAX_CLIPPED_FRAC:
        p.append("clipped audio")
    if f["snr_db"] < MIN_SNR_DB:
        p.append("noisy audio")
    if f.get("voiced_frac", 0.0) < MIN_VOICED_FRAC or np.isnan(f.get("f0_median_st", np.nan)):
        p.append("too little voiced speech for pitch")
    return p


@dataclass
class SpeakerBaseline:
    """Earlier usable utterances from the same speaker. Robust centre/spread (median, MAD)."""

    min_n: int = field(default_factory=lambda: MIN_BASELINE_UTTS)
    rows: list[dict[str, float]] = field(default_factory=list)
    streak: int = 0
    last_z: dict[str, float] = field(default_factory=dict)

    def add(self, f: dict[str, float]) -> None:
        self.rows.append({k: f[k] for k in FEATURES})

    @property
    def ready(self) -> bool:
        return len(self.rows) >= self.min_n

    def zscores(self, f: dict[str, float]) -> dict[str, float]:
        """Signed z of `f` vs the baseline: (x - median) / max(1.4826*MAD, floor)."""
        z = {}
        for k in FEATURES:
            vals = np.array([r[k] for r in self.rows], dtype=np.float64)
            med = float(np.median(vals))
            spread = max(1.4826 * float(np.median(np.abs(vals - med))), Z_FLOORS[k])
            z[k] = (f[k] - med) / spread
        return z


_MARKER_TEXT = {
    ("f0_median_st", 1): "higher pitch than this speaker's earlier delivery",
    ("f0_median_st", -1): "lower pitch than this speaker's earlier delivery",
    ("f0_std_st", 1): "more pitch variation than earlier",
    ("f0_std_st", -1): "flatter pitch than earlier",
    ("rms_db", 1): "louder than earlier",
    ("rms_db", -1): "quieter than earlier",
    ("rate_proxy", 1): "faster speech than earlier (rough proxy)",
    ("rate_proxy", -1): "slower speech than earlier (rough proxy)",
    ("pause_frac", 1): "more pausing than earlier",
    ("pause_frac", -1): "less pausing than earlier",
}


def assess(f: dict[str, float] | None, base: SpeakerBaseline) -> dict:
    """`_assess` plus `delivery_change`, the neutral name for `stress_related_change` (same value).
    The score is sign-agnostic (abs z), so quieter/flatter/slower speech raises it too; user-facing
    text should say "change vs earlier delivery", not stress."""
    d = _assess(f, base)
    d["delivery_change"] = d["stress_related_change"]
    return d


def _assess(f: dict[str, float] | None, base: SpeakerBaseline) -> dict:
    """Compare one utterance with the baseline. Returns the `details` payload:

    status               ok | building_baseline | insufficient_evidence
    stress_related_change  float in [0,1] or None (sustained change vs own baseline)
    delivery_markers     list[str] hedged observations (may be empty)
    emotion_estimate     None (not computed in this module; see plan task 2.2)
    calibration_status   always 'not_established'
    z                    per-feature signed z-scores when computed

    Baseline updates: usable utterances join the baseline only while it is not ready, so a
    long pressure run cannot drag the baseline along with it."""
    base_details = {"emotion_estimate": None, "calibration_status": "not_established"}
    problems = quality_problems(f)
    if problems:
        base.streak = 0
        return {**base_details, "status": "insufficient_evidence", "stress_related_change": None,
                "delivery_markers": [], "quality_problems": problems}
    assert f is not None
    if not base.ready:
        base.add(f)
        return {**base_details, "status": "building_baseline", "stress_related_change": None,
                "delivery_markers": [], "baseline_n": len(base.rows)}
    z = base.zscores(f)
    hits = {k: v for k, v in z.items() if abs(v) >= Z_FIRE}
    if len(hits) < MIN_FEATS:
        hits = {}
    base.streak = base.streak + 1 if hits else 0
    base.last_z = z
    markers: list[str] = []
    change: float | None = 0.0
    if base.streak >= SUSTAIN_N:
        markers = [_MARKER_TEXT[(k, 1 if v > 0 else -1)] for k, v in sorted(hits.items(), key=lambda kv: -abs(kv[1]))]
        change = float(np.clip((max(abs(v) for v in hits.values()) - Z_FIRE + 1.0) / 3.0, 0.0, 1.0))
    return {**base_details, "status": "ok", "stress_related_change": change, "delivery_markers": markers,
            "z": {k: round(v, 2) for k, v in z.items()}, "baseline_n": len(base.rows), "streak": base.streak,
            "features": {k: round(f[k], 2) for k in FEATURES}}
