import numpy as np

from core import Utterance
from providers.stt_stub import SidecarTranscriptSTT
from segmenter import EnergyVAD

SR = 16_000


def tone(seconds, amp=0.3):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds):
    return np.zeros(int(seconds * SR), dtype=np.float32)


def test_energy_vad_splits_bursts_streaming():
    audio = np.concatenate([silence(0.5), tone(1.0), silence(1.0), tone(0.8), silence(1.0), tone(0.1), silence(1.0)])
    vad = EnergyVAD(sample_rate=SR)
    segs = []
    for i in range(0, len(audio), 1600):  # 100 ms chunks, like the WS stream
        segs += vad.feed(audio[i:i + 1600])
    segs += vad.flush()
    assert len(segs) == 2  # the 0.1 s blip is below min_speech_ms
    assert abs(segs[0].t_start - 0.5) < 0.2
    assert abs(segs[1].t_start - 2.5) < 0.2
    assert 0.9 < segs[0].t_end - segs[0].t_start < 1.5


def test_flush_returns_in_progress_utterance():
    vad = EnergyVAD(sample_rate=SR)
    assert vad.feed(tone(1.0)) == []
    segs = vad.flush()
    assert len(segs) == 1


def _utt(i, t0, t1):
    return Utterance(id=i, audio=np.zeros(1, np.float32), sample_rate=SR, t_start=t0, t_end=t1)


async def test_sidecar_timed_lines_follow_vad_windows():
    stt = SidecarTranscriptSTT(["# comment", "[0.5] one", "[2.0] two", "[2.6] three", "[9.0] tail"])
    assert await stt.transcribe(_utt(0, 0.4, 1.8)) == "one"
    assert await stt.transcribe(_utt(1, 1.9, 4.0)) == "two three"  # VAD merged two lines
    assert stt.finalize() == "tail"


async def test_sidecar_untimed_lines_sequential():
    stt = SidecarTranscriptSTT(["a", "", "b"])
    assert await stt.transcribe(_utt(0, 0, 1)) == "a"
    assert await stt.transcribe(_utt(1, 1, 2)) == "b"
    assert await stt.transcribe(_utt(2, 2, 3)) == ""
