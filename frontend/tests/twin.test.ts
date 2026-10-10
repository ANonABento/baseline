import { test } from "node:test";
import assert from "node:assert/strict";
import type { SignalEvent } from "../src/types.ts";
import type { Line } from "../src/lib/session.ts";
import { changeByPressure, twinView } from "../src/lib/twin.ts";

const line = (id: number, speaker: "ai" | "visitor", t0: number, t1: number, text: string): Line => ({
  type: "transcript", utterance_id: id, t_start: t0, t_end: t1, text, speaker, analyzed: false,
});
const sig = (id: number, details: Record<string, unknown>): SignalEvent => ({
  type: "signal", utterance_id: id, signal: "prosody", score: 0, confidence: 0.25, reason: "", details, latency_ms: 0,
});

const base = {
  lines: [
    line(1000, "ai", 0, 3, "Hi this is Margaret"),
    line(0, "visitor", 4, 6, "Can I verify your date of birth"),
    line(1001, "ai", 7, 9, "Do it now"),
    line(1, "visitor", 12, 16, "I will not do that"),
  ],
  signals: [
    sig(0, { status: "building_baseline", baseline_n: 1, delivery_change: null }),
    sig(1, { status: "ok", baseline_n: 3, delivery_change: 0.6, delivery_markers: ["louder than earlier"], z: { f0_median_st: 3.5, rms_db: -0.5 }, features: { pause_frac: 0.2 } }),
  ],
  pressure: [{ utterance_id: 1000, level: 1, t: 0 }, { utterance_id: 1001, level: 3, t: 7 }],
  decisions: [{ utterance_id: 1, event: "refused" as const, t: 12 }],
};

test("known answers: latency, speech rate, pressure level, baseline progress", () => {
  const v = twinView(base);
  assert.equal(v.turns.length, 2);
  assert.equal(v.turns[0].latency_s, 1); // 4 - 3
  assert.equal(v.turns[1].latency_s, 3); // 12 - 9
  assert.equal(v.turns[0].wps, 7 / 2); // 7 words in 2 s
  assert.deepEqual(v.turns.map((t) => t.pressure), [1, 3]);
  assert.equal(v.pressureNow, 3);
  assert.equal(v.baselineN, 3);
  assert.equal(v.baselineReady, true);
  assert.deepEqual(v.markers, ["louder than earlier"]);
  assert.equal(v.latest?.maxAbsZ, 3.5);
  assert.deepEqual(changeByPressure(v.turns), [{ level: 3, mean: 3.5, n: 1 }]);
});

test("while building the baseline there is no gauge and no markers", () => {
  const v = twinView({ ...base, lines: base.lines.slice(0, 2), signals: [base.signals[0]], pressure: [], decisions: [] });
  assert.equal(v.baselineReady, false);
  assert.equal(v.baselineN, 1);
  assert.equal(v.z, null);
  assert.deepEqual(v.markers, []);
  assert.equal(v.pressureNow, null);
});

test("typed turns have no duration, so no speech rate", () => {
  const v = twinView({ ...base, lines: [line(2, "visitor", 5, 5, "I refuse")], signals: [], pressure: [], decisions: [] });
  assert.equal(v.turns[0].wps, null);
  assert.equal(v.turns[0].status, "none");
});
