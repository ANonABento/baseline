import { test } from "node:test";
import assert from "node:assert/strict";
import type { ServerMsg } from "../src/lib/contract.ts";
import { eventsFromBackend, replay } from "../src/lib/reports.ts";
import { INITIAL, sessionReducer, type SessionAction, type SessionState } from "../src/lib/session.ts";

const run = (actions: SessionAction[], s: SessionState = INITIAL) => actions.reduce(sessionReducer, s);
const msg = (m: ServerMsg, now = 0): SessionAction => ({ kind: "msg", msg: m, now });
const started: ServerMsg = {
  type: "call_started", session_id: "s1", role: "agent", scenario: "account_takeover", voice: "aria",
  customer: { id: "C1", name: "Margaret Chen", account_mask: "••4217", enrolled: true },
  audio: { sample_rate: 16000, format: "pcm_s16le" }, max_call_s: 180,
};
const ended: ServerMsg = {
  type: "call_ended", reason: "visitor_hung_up", report_id: "r1",
  reveal: { role: "agent", scenario: "account_takeover", persona_label: "Clone", voice: "aria", tts: "kokoro" },
};

test("lobby -> requesting -> queued -> live -> ended", () => {
  let s = run([{ kind: "request" }]);
  assert.equal(s.phase, "requesting");
  s = run([msg({ type: "queue", position: 2, queue_length: 3, eta_s: 40 })], s);
  assert.equal(s.phase, "queued");
  assert.deepEqual(s.queue, { position: 2, queue_length: 3, eta_s: 40 });
  s = run([msg({ type: "queue", position: 1, queue_length: 2, eta_s: 10 })], s);
  assert.equal(s.queue?.position, 1);
  s = run([msg(started, 1000)], s);
  assert.equal(s.phase, "live");
  assert.equal(s.startedAt, 1000);
  assert.equal(s.queue, null);
  s = run([msg(ended, 9000)], s);
  assert.equal(s.phase, "ended");
  assert.equal(s.endedAt, 9000);
  assert.equal(s.ended?.report_id, "r1");
});

test("call_started can arrive without any queue message", () => {
  const s = run([{ kind: "request" }, msg(started)]);
  assert.equal(s.phase, "live");
});

test("cancel returns to the lobby and ignores late messages", () => {
  const s = run([{ kind: "request" }, msg({ type: "queue", position: 1, queue_length: 1, eta_s: 5 }), { kind: "cancel" }, msg(started)]);
  assert.equal(s.phase, "lobby");
  assert.equal(s.call, null);
});

test("socket drops: while waiting -> error, mid-call -> ended with a reason", () => {
  assert.equal(run([{ kind: "request" }, { kind: "closed", now: 1 }]).phase, "error");
  const s = run([{ kind: "request" }, msg(started), { kind: "closed", now: 5 }]);
  assert.equal(s.phase, "ended");
  assert.ok(s.error);
  // closing after a clean end changes nothing
  const done = run([{ kind: "request" }, msg(started), msg(ended, 3)]);
  assert.equal(run([{ kind: "closed", now: 9 }], done), done);
});

test("server error before the call is fatal, during the call it's informational", () => {
  assert.equal(run([{ kind: "request" }, msg({ type: "error", message: "full" })]).phase, "error");
  const s = run([{ kind: "request" }, msg(started), msg({ type: "error", message: "tts hiccup" })]);
  assert.equal(s.phase, "live");
  assert.equal(s.error, "tts hiccup");
});

test("live events: transcript upsert, signals, trust, alert peak, speaking", () => {
  const s = run([
    { kind: "request" },
    msg(started, 0),
    msg({ type: "speaking", who: "ai", state: "start" }),
    msg({ type: "transcript", utterance_id: 1, t_start: 0, t_end: 2, text: "Hi", speaker: "ai", analyzed: true }),
    msg({ type: "transcript", utterance_id: 1, t_start: 0, t_end: 2.5, text: "Hi there", speaker: "ai", analyzed: true }),
    msg({ type: "signal", utterance_id: 1, signal: "fraud", score: 0.9, confidence: 0.8, reason: "x", details: { patterns: [{ id: "p", name: "P", severity: "high", quote: "there", utterance_id: 1 }] } }),
    msg({ type: "trust", score: 40 }, 2000),
    msg({ type: "alert", level: "high", reasons: [], suggested_action: "", signals: ["fraud"], citations: [] }),
    msg({ type: "alert", level: "caution", reasons: [], suggested_action: "", signals: ["fraud"], citations: [] }),
    msg({ type: "ai_level", rms: 0.5 }),
  ]);
  assert.equal(s.lines.length, 1);
  assert.equal(s.lines[0].text, "Hi there");
  assert.equal(s.speaking.ai, true);
  assert.equal(s.signals.length, 1);
  assert.equal(s.evidence.items[0].id, "p");
  assert.equal(s.trust, 40);
  assert.deepEqual(s.trustHistory, [{ t: 2, score: 40 }]);
  assert.equal(s.alert?.level, "caution");
  assert.equal(s.peak, "high");
});

test("backend report normalizes into a replayable call", () => {
  const events = eventsFromBackend("r9", {
    session: { role: "agent", scenario: "grandparent", voice: "june", customer: { name: "Walter", account_mask: "••1983", enrolled: true }, duration_s: 30 },
    reveal: { persona_label: "Coached customer", tts: "kokoro" },
    transcript: [
      { utterance_id: 2, t_start: 5, t_end: 8, text: "He's in jail", speaker: "ai" },
      { utterance_id: 1, t_start: 0, t_end: 3, text: "Hello", speaker: "ai" },
    ],
    signals: [{ utterance_id: 2, signal: "fraud", score: 0.85, confidence: 0.8, reason: "bail", details: {} }],
    alerts: [{ level: "high", utterance_id: 2, reasons: ["bail"], signals: ["fraud"] }],
    something_new: { ignored: true },
  });
  const s = replay(events);
  assert.equal(s.phase, "ended");
  assert.deepEqual(s.lines.map((l) => l.utterance_id), [1, 2]);
  assert.equal(s.peak, "high");
  assert.equal(s.call?.customer.name, "Walter");
  assert.equal(s.ended?.reveal.persona_label, "Coached customer");
  assert.equal(s.endedAt, 30000);
});

test("live backend report shape (meta / durations / ended_reason / timed signals)", () => {
  const s = replay(eventsFromBackend("abc", {
    id: "abc", ended_reason: "hangup",
    meta: { role: "agent", scenario: "account_takeover", voice: "Rachel", tts: "elevenlabs", persona: { label: "Fraudster cloning Margaret", summary: "x" },
      customer: { id: "CUST-004217", name: "Margaret Chen", account_mask: "••4217", enrolled: true } },
    durations: { queue_wait_s: 0, call_s: 42 },
    transcript: [
      { utterance_id: 0, speaker: "ai", analyzed: true, text: "Hi, it's Margaret", t_start: 0.5, t_end: 3 },
      { utterance_id: 1000, speaker: "visitor", analyzed: false, text: "Hello", t_start: 3.5, t_end: 4 },
    ],
    signals: [{ utterance_id: 0, signal: "spoof", score: 0.8, confidence: 0.7, reason: "synthetic", details: {}, t: 3.6 }],
    alerts: [{ level: "caution", reasons: ["synthetic"], suggested_action: "verify", signals: ["spoof"], citations: [], t: 3.7 }],
    verdict: { level: "caution" },
  }));
  assert.equal(s.ended?.reason, "hangup");
  assert.equal(s.ended?.reveal.persona_label, "Fraudster cloning Margaret");
  assert.equal(s.ended?.reveal.tts, "elevenlabs");
  assert.equal(s.endedAt, 42000);
  assert.deepEqual(s.lines.map((l) => [l.utterance_id, l.speaker]), [[0, "ai"], [1000, "visitor"]]);
  assert.equal(s.signals.length, 1);
  assert.equal(s.peak, "caution");
});

test("queue position 0 (immediate slot) then call_started", () => {
  const s = run([{ kind: "request" }, msg({ type: "queue", position: 0, queue_length: 0, eta_s: 0 }), msg(started)]);
  assert.equal(s.phase, "live");
});
