"""Real-model plumbing. Pure-numpy helpers always run; model tests skip without the `ml`
extra (uv sync --extra ml) and need the weights in the HF cache."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from detectors.speaker import SpeakerDetector, make_speaker_detector, similarity_to_risk
from detectors.spoof import SpoofDetector, make_spoof_detector
from ml import voiceprints
from ml.audio import read_audio, windows
from segmenter import EnergyVAD, make_segmenter
from settings import Settings

DEMO = Path(__file__).resolve().parent.parent / "data" / "demo"
SR = 16_000


def has(*mods):
    return all(importlib.util.find_spec(m) is not None for m in mods)


# ------------------------------------------------------------------ always-on


def test_similarity_to_risk_anchors_and_monotonic():
    assert similarity_to_risk(0.55, 0.55, 0.30) == pytest.approx(0.1, abs=1e-6)
    assert similarity_to_risk(0.30, 0.55, 0.30) == pytest.approx(0.9, abs=1e-6)
    sims = np.linspace(-0.2, 1.0, 50)
    risks = [similarity_to_risk(s, 0.55, 0.30) for s in sims]
    assert all(a >= b for a, b in zip(risks, risks[1:]))
    with pytest.raises(ValueError):
        similarity_to_risk(0.5, 0.3, 0.6)


def test_windows_equal_length_and_cover_tail():
    a = np.arange(int(9.5 * SR), dtype=np.float32)
    w = windows(a, SR, 4.0, 2.0)
    assert {len(x) for x in w} == {4 * SR}
    assert w[-1][-1] == a[-1]
    assert windows(a[: SR // 2], SR, 4.0, 2.0, min_s=1.0) == []
    assert len(windows(a[: 2 * SR], SR, 4.0, 2.0, min_s=1.0)) == 1


def test_voiceprint_roundtrip_and_id_validation(tmp_path):
    e = np.random.default_rng(0).standard_normal(192).astype(np.float32)
    voiceprints.save(tmp_path, "CUST-1", e, {"name": "Test"})
    vp = voiceprints.load(tmp_path, "CUST-1")
    assert vp is not None and vp.name == "Test"
    assert np.linalg.norm(vp.embedding) == pytest.approx(1.0, abs=1e-5)
    assert voiceprints.list_enrolled(tmp_path)[0]["id"] == "CUST-1"
    for bad in ("../x", "a/b", "", "..", ".hidden"):
        assert not voiceprints.valid_customer_id(bad)
        assert voiceprints.load(tmp_path, bad) is None


def test_stub_settings_give_stub_components():
    s = Settings(speaker_provider="stub", spoof_provider="stub", vad_provider="energy")
    assert isinstance(make_speaker_detector(s), SpeakerDetector)
    assert isinstance(make_spoof_detector(s), SpoofDetector)
    assert isinstance(make_segmenter(s), EnergyVAD)


def test_wavlm_without_trained_model_falls_back_to_stub(tmp_path):
    s = Settings(spoof_provider="wavlm", spoof_lr_path=tmp_path / "missing.joblib")
    assert isinstance(make_spoof_detector(s), SpoofDetector)


def test_eval_wer():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from eval import wer

    assert wer("Hi, this is Margaret.", "hi this is margaret") == 0.0
    assert wer("hi this margaret", "hi this is margaret") == 0.25


# ------------------------------------------------------------------ real models

needs_demo = pytest.mark.skipif(not (DEMO / "takeover_clone.wav").exists(), reason="demo clips missing")


@needs_demo
@pytest.mark.skipif(not has("silero_vad", "torch"), reason="ml extra not installed")
def test_silero_vad_streaming_splits_demo_clip():
    from segmenter import SileroVAD

    vad = SileroVAD()
    audio = read_audio(DEMO / "takeover_clone.wav")
    segs = []
    for i in range(0, len(audio), 1600):
        segs += vad.feed(audio[i:i + 1600])
    segs += vad.flush()
    assert len(segs) == 5  # one per scripted sentence
    starts = [0.50, 6.07, 11.15, 16.47, 19.79]
    for seg, t in zip(segs, starts):
        assert abs(seg.t_start - t) < 0.4


@needs_demo
@pytest.mark.skipif(not has("speechbrain", "torch"), reason="ml extra not installed")
async def test_ecapa_same_voice_matches_different_voice_does_not(tmp_path):
    from core import CallContext, Utterance
    from detectors.speaker import EcapaSpeakerDetector
    from ml.ecapa import EcapaEncoder

    s = Settings(speaker_provider="ecapa", enroll_dir=tmp_path)
    enc = EcapaEncoder.get(s.speaker_model, s.pretrained_dir, s.speaker_device)
    samantha = read_audio(DEMO / "benign_balance.wav")  # enroll on one Samantha clip
    embs = enc.embed_long(samantha)
    voiceprints.save(tmp_path, "CUST-T", np.mean(embs, axis=0), {"name": "T"})
    det = EcapaSpeakerDetector(s)
    ctx = CallContext(customer_id="CUST-T")

    async def risk(path, t0, t1):
        a = read_audio(path)[int(t0 * SR):int(t1 * SR)]
        return await det.analyze(Utterance(0, a, SR, t0, t1), ctx)

    same = await risk(DEMO / "takeover_clone.wav", 0.4, 5.4)  # Samantha, different words
    diff = await risk(DEMO / "grandparent_vulnerable.wav", 0.4, 5.0)  # Moira
    assert same.details["similarity"] > s.speaker_accept_sim and same.score < 0.2
    assert diff.details["similarity"] < s.speaker_reject_sim + 0.05 and diff.score > 0.7
    nobody = await det.analyze(Utterance(0, samantha[:SR * 3], SR, 0, 3), CallContext(customer_id="NOPE"))
    assert nobody.confidence == 0.0


@needs_demo
@pytest.mark.skipif(not has("transformers", "torch"), reason="ml extra not installed")
async def test_pretrained_spoof_flags_say_tts():
    from core import CallContext, Utterance
    from detectors.spoof import PretrainedSpoofDetector

    det = PretrainedSpoofDetector(Settings(spoof_provider="pretrained"))
    a = read_audio(DEMO / "benign_balance.wav")[int(0.4 * SR):int(5.0 * SR)]
    r = await det.analyze(Utterance(0, a, SR, 0.4, 5.0), CallContext())
    assert r.score > 0.8 and r.confidence > 0.5  # macOS `say` is synthetic speech


@needs_demo
@pytest.mark.skipif(not has("mlx_whisper"), reason="mlx-whisper not installed")
async def test_mlx_whisper_transcribes_utterance():
    from core import Utterance
    from providers.stt_mlx import MlxWhisperSTT

    stt = MlxWhisperSTT("mlx-community/whisper-small-mlx")  # small: faster to load in tests
    a = read_audio(DEMO / "takeover_clone.wav")[int(11.0 * SR):int(16.2 * SR)]
    text = (await stt.transcribe(Utterance(0, a, SR, 11.0, 16.2))).lower()
    assert "wire" in text and "account" in text
