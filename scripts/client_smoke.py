"""Scripted visitor for a live role-client call (no browser, typed turns).

    uv run --project backend python scripts/client_smoke.py --url http://127.0.0.1:8010 --scenario grandchild

Waits for the AI caller to finish each turn, then types the next visitor line. The last lines start
reading out a card number, which should drive caution -> intervention -> high -> Baseline's voice
(binary frames between baseline_audio_start/end) + actions. Prints a timeline and per-turn latency
(visitor text sent -> first AI audio frame), then fetches the report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx
import websockets

TURNS = {
    "grandchild": [
        "Ethan? Oh no, what happened? Are you okay?",
        "Oh my goodness. How much do you need, sweetheart?",
        "Okay, okay. I have a gift card here already, let me get my card.",
        "The numbers on the back are 4 1 2 7 8 8 3 9 0 2 1 1",
    ],
    "fake_bank": [
        "Oh, no, I didn't make that charge. What do I do?",
        "Okay, I got a text. Hold on.",
        "The code is 4 8 2 9 1 7",
        "Okay, which account should I move it to?",
    ],
    "irs": [
        "What? I paid my taxes. What is this about?",
        "Please, I don't want to be arrested. How much is it?",
        "Okay, which store should I go to?",
        "I have the card, the numbers are 6 1 2 2 9 9 0 3",
    ],
    "tech_support": [
        "Oh dear, a virus? What should I do?",
        "Okay, I'm installing AnyDesk on my computer now.",
        "The access code is 3 3 1 9 0 2 7 7 1",
        "Okay, I'll send the difference back.",
    ],
}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--scenario", default="grandchild")
    ap.add_argument("--voice", default="random")
    ap.add_argument("--suspect-after", type=int, default=2, help="press 'This feels like a scam' after N turns")
    a = ap.parse_args()

    async with httpx.AsyncClient(base_url=a.url, timeout=10) as http:
        cfg = (await http.get("/api/config")).json()
        print("config: tts=%s caller_llm=%s" % (cfg["tts"], cfg.get("caller_llm")))
        s = (await http.post("/api/session", json={"role": "client", "scenario": a.scenario, "voice": a.voice})).json()
    t0 = time.monotonic()
    rel = lambda: f"{time.monotonic() - t0:6.2f}"  # noqa: E731
    turns = list(TURNS[a.scenario])
    sent_at: float | None = None
    latencies: list[float] = []
    ai_frames = baseline_frames = 0
    in_baseline = False
    seen: dict[str, int] = {}
    report_id = None
    async with websockets.connect(s["ws_url"], max_size=None) as ws:
        n_turn = 0
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=25)
            except asyncio.TimeoutError:  # the AI went quiet: speak again, or end the call
                print(f"{rel()}  (idle 25 s)")
                if turns:
                    n_turn += 1
                    await ws.send(json.dumps({"type": "text", "text": turns.pop(0)}))
                    sent_at = time.monotonic()
                else:
                    await ws.send(json.dumps({"type": "hangup"}))
                continue
            if isinstance(raw, bytes):
                if in_baseline:
                    baseline_frames += 1
                else:
                    ai_frames += 1
                    if sent_at is not None:
                        latencies.append(time.monotonic() - sent_at)
                        print(f"{rel()}  first AI audio {latencies[-1] * 1000:.0f} ms after visitor text")
                        sent_at = None
                continue
            m = json.loads(raw)
            typ = m["type"]
            seen[typ] = seen.get(typ, 0) + 1
            if typ in ("ai_level", "pong", "trust"):
                continue
            if typ == "transcript":
                print(f"{rel()}  [{m['speaker']}] {m['text']}")
            elif typ == "signal":
                if m["score"] >= 0.5 and m["confidence"] > 0:
                    print(f"{rel()}  signal {m['signal']} {m['score']:.2f} {m['reason'][:70]}")
            elif typ == "alert":
                print(f"{rel()}  ALERT {m['level']} {m['signals']}")
            elif typ == "intervention":
                print(f"{rel()}  INTERVENTION {m['level']} {m['reason_id']}: {m['message']}")
            elif typ == "baseline_audio_start":
                in_baseline = True
                print(f"{rel()}  baseline_audio_start")
            elif typ == "baseline_audio_end":
                in_baseline = False
                print(f"{rel()}  baseline_audio_end ({baseline_frames} frames)")
            elif typ == "action":
                print(f"{rel()}  ACTION {m['kind']}: {m['message']}")
            elif typ == "suspect_ack":
                print(f"{rel()}  suspect recorded at {m['t']}")
            elif typ == "call_ended":
                report_id = m["report_id"]
                print(f"{rel()}  call_ended {m['reason']} you_vs_baseline={m['reveal'].get('you_vs_baseline')}")
                break
            elif typ in ("call_started", "queue", "stop_audio", "error", "warning"):
                print(f"{rel()}  {typ} {json.dumps(m)[:160]}")
            if typ == "speaking" and m["who"] == "ai" and m["state"] == "end":
                await asyncio.sleep(0.6)
                if not turns:
                    if baseline_frames or seen.get("intervention", 0) >= 2:
                        await ws.send(json.dumps({"type": "hangup"}))
                    continue
                if n_turn == a.suspect_after:
                    await ws.send(json.dumps({"type": "suspect"}))
                line = turns.pop(0)
                n_turn += 1
                await ws.send(json.dumps({"type": "text", "text": line}))
                sent_at = time.monotonic()
            if typ == "baseline_audio_end" and not turns:
                await asyncio.sleep(1.0)
                await ws.send(json.dumps({"type": "hangup"}))
    async with httpx.AsyncClient(base_url=a.url, timeout=10) as http:
        r = (await http.get(f"/api/report/{report_id}")).json()
    print("\nreport: level=%s interventions=%s actions=%s suspicion=%s you_vs_baseline=%s" % (
        r["verdict"]["level"], [(i["t"], i["level"], i["reason_id"], i["spoken"]) for i in r["interventions"]],
        [a["kind"] for a in r["actions"]], r["suspicion"], r["you_vs_baseline"]))
    print("ai frames %d, baseline frames %d" % (ai_frames, baseline_frames))
    print("turn latency (text -> first AI audio, client side): %s" % [round(x * 1000) for x in latencies])
    print("server turns:", [(t["visitor_end_to_first_audio_ms"], t["llm_first_sentence_ms"], t["tts_first_audio_ms"])
                            for t in r["latencies"]["turns"]])
    print("mean/p50/max:", r["latencies"]["mean_turn_ms"], r["latencies"]["p50_turn_ms"], r["latencies"]["max_turn_ms"])
    print("errors:", r["errors"])


if __name__ == "__main__":
    asyncio.run(main())
