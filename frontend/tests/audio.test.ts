import { test } from "node:test";
import assert from "node:assert/strict";
import { pcm16ToFloat, planChunk, rms } from "../src/lib/audio.ts";

test("chunks queue back to back without gaps", () => {
  let st = { nextTime: 0 };
  const starts: number[] = [];
  for (let i = 0; i < 4; i++) {
    const p = planChunk(st, 10 + i * 0.01, 0.1, 0.08);
    starts.push(+p.startAt.toFixed(6));
    st = p.state;
  }
  assert.deepEqual(starts, [10.08, 10.18, 10.28, 10.38]);
});

test("underrun restarts after the lead-in instead of scheduling in the past", () => {
  const p = planChunk({ nextTime: 5 }, 9, 0.1, 0.05);
  assert.equal(p.restarted, true);
  assert.equal(p.startAt, 9.05);
  assert.ok(Math.abs(p.state.nextTime - 9.15) < 1e-9);
});

test("a runaway backlog is dropped", () => {
  const p = planChunk({ nextTime: 30 }, 10, 0.1, 0.05, 8);
  assert.equal(p.restarted, true);
  assert.equal(p.startAt, 10.05);
});

test("still-queued audio is not restarted", () => {
  const p = planChunk({ nextTime: 10.5 }, 10, 0.1);
  assert.equal(p.restarted, false);
  assert.equal(p.startAt, 10.5);
});

test("pcm16 conversion and rms", () => {
  const i16 = new Int16Array([0, 16384, -32768, 32767]);
  const f = pcm16ToFloat(i16.buffer);
  assert.deepEqual([...f].map((x) => +x.toFixed(4)), [0, 0.5, -1, 1]);
  assert.equal(rms(new Float32Array([0.5, -0.5])), 0.5);
  assert.equal(rms(new Float32Array()), 0);
  // odd byte length is truncated, not thrown on
  assert.equal(pcm16ToFloat(new ArrayBuffer(5)).length, 2);
});
