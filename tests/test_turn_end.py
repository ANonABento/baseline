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
                           _ending=False)


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
