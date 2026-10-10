"""End-of-turn hold: the AI doesn't answer a mid-thought pause."""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from caller.live_call import LiveCall, VisitorTurn, looks_unfinished  # noqa: E402


@pytest.mark.parametrize("text", ["Yeah, I did get a text, but", "I think so, um", "Well,", "It was my",
                                  "Hang on and", "So the", "I mean"])
def test_unfinished(text):
    assert looks_unfinished(text)


@pytest.mark.parametrize("text", ["No.", "Yes", "Who is this?", "okay", "Hello?", "Not interested.",
                                  "I didn't make that purchase.", "Can you tell me your name?", ""])
def test_finished(text):
    assert not looks_unfinished(text)


def _fake(silence_ms=200, extra_ms=400):
    return SimpleNamespace(settings=SimpleNamespace(turn_end_silence_ms=silence_ms, turn_unfinished_extra_ms=extra_ms),
                           visitor_speaking=False, _last_speech_at=time.monotonic(), turn_q=asyncio.Queue(),
                           _ending=False, ptt_mode=False, ptt_active=False, _transcribing=lambda: False)


def _turn(text, source="audio"):
    return VisitorTurn(text, 0, 1, time.monotonic(), source)


def test_complete_turn_waits_only_base_silence():
    async def run():
        call = _fake()
        t0 = time.monotonic()
        turns = [_turn("Who is this?")]
        await LiveCall._hold_for_end_of_turn(call, turns)
        return time.monotonic() - t0, turns
    dt, turns = asyncio.run(run())
    assert 0.15 <= dt < 0.4 and len(turns) == 1


def test_unfinished_turn_merges_continuation():
    async def run():
        call = _fake()
        turns = [_turn("Yeah I got a text but")]

        async def resume():
            await asyncio.sleep(0.3)  # past the base silence, inside the unfinished extra
            call._last_speech_at = time.monotonic()
            call.turn_q.put_nowait(_turn("I didn't click it."))
        asyncio.create_task(resume())
        await LiveCall._hold_for_end_of_turn(call, turns)
        return turns
    turns = asyncio.run(run())
    assert [t.text for t in turns] == ["Yeah I got a text but", "I didn't click it."]


def test_typed_turn_skips_hold():
    async def run():
        call = _fake(silence_ms=2000)
        t0 = time.monotonic()
        await LiveCall._hold_for_end_of_turn(call, [_turn("and", source="text")])
        return time.monotonic() - t0
    assert asyncio.run(run()) < 0.05


def test_ptt_release_skips_silence_hold():
    async def run():
        call = _fake(silence_ms=2000)
        call.ptt_mode = True
        t0 = time.monotonic()
        await LiveCall._hold_for_end_of_turn(call, [_turn("Yeah I got a text but")])
        return time.monotonic() - t0
    assert asyncio.run(run()) < 0.05


def test_ptt_waits_while_held_and_merges():
    async def run():
        call = _fake(silence_ms=2000)
        call.ptt_mode, call.ptt_active = True, True
        turns = [_turn("Yeah I got a text but")]

        async def keep_talking_then_release():
            await asyncio.sleep(0.2)
            call.turn_q.put_nowait(_turn("I didn't click it."))
            await asyncio.sleep(0.1)
            call.ptt_active = False
        asyncio.create_task(keep_talking_then_release())
        t0 = time.monotonic()
        await LiveCall._hold_for_end_of_turn(call, turns)
        return time.monotonic() - t0, turns
    dt, turns = asyncio.run(run())
    assert dt < 0.5 and [t.text for t in turns] == ["Yeah I got a text but", "I didn't click it."]


def test_client_visitor_lines_use_call_time():
    """Push-to-talk sends mic audio in bursts: segment times (mic seconds) must map to call time."""
    import numpy as np

    async def run():
        lines = []

        async def visitor_line(text, t0, t1, ms=None):
            lines.append((text, t0, t1))

        async def transcribe(_utt):
            return "Who is this?"

        call = SimpleNamespace(settings=SimpleNamespace(sample_rate=16000), stt=SimpleNamespace(transcribe=transcribe),
                               col=SimpleNamespace(errors=[]), _ending=False, candidate=False, turn_q=asyncio.Queue(),
                               _mic_to_call_time=lambda t: round(t + 12.0, 2), _visitor_line=visitor_line)
        seg = SimpleNamespace(audio=np.zeros(16000, dtype=np.float32))
        await LiveCall._stt_one(call, seg, None, 0, 1.0, 2.0, time.perf_counter())
        return lines, call.turn_q.get_nowait()
    lines, turn = asyncio.run(run())
    assert lines == [("Who is this?", 13.0, 14.0)] and (turn.t_start, turn.t_end) == (13.0, 14.0)
