import { test } from "node:test";
import assert from "node:assert/strict";
import { activeLineAt, audioFromBackend } from "../src/lib/reports.ts";

const line = (id: number, t0: number, t1: number) => ({ utterance_id: id, t_start: t0, t_end: t1 });
const lines = [line(1, 0, 4), line(2, 4, 9), line(3, 10, 15)];

test("activeLineAt: half-open intervals, gaps and the end return null", () => {
  assert.equal(activeLineAt(lines, 0)?.utterance_id, 1);
  assert.equal(activeLineAt(lines, 3.99)?.utterance_id, 1);
  assert.equal(activeLineAt(lines, 4)?.utterance_id, 2);
  assert.equal(activeLineAt(lines, 9.5), null);
  assert.equal(activeLineAt(lines, 15), null);
  assert.equal(activeLineAt([], 1), null);
});

test("activeLineAt: on overlap the later-starting line wins", () => {
  assert.equal(activeLineAt([line(1, 0, 10), line(2, 5, 7)], 6)?.utterance_id, 2);
  assert.equal(activeLineAt([line(2, 5, 7), line(1, 0, 10)], 8)?.utterance_id, 1);
});

test("audioFromBackend: missing or malformed is null, visitor channel normalized", () => {
  assert.equal(audioFromBackend({}), null);
  assert.equal(audioFromBackend({ audio: null }), null);
  assert.equal(audioFromBackend({ audio: { duration_s: 3 } }), null);
  assert.deepEqual(audioFromBackend({ audio: { url: "/api/report/x/audio", duration_s: 42.5, channels: { left: "ai", right: "visitor" } } }), {
    url: "/api/report/x/audio",
    duration_s: 42.5,
    channels: { left: "ai", right: "visitor" },
  });
  assert.equal(audioFromBackend({ audio: { url: "/a", duration_s: 1, channels: { left: "ai", right: null } } })?.channels.right, null);
});
