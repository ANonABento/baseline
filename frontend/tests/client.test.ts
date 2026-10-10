// Role client: interventions, actions, "This feels like a scam", client notes, report replay.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ServerMsg } from "../src/lib/contract.ts";
import { buildNotes } from "../src/lib/notes.ts";
import { eventsFromBackend, replay } from "../src/lib/reports.ts";
import { INITIAL, sessionReducer, type SessionAction, type SessionState } from "../src/lib/session.ts";

const run = (actions: SessionAction[], s: SessionState = INITIAL) => actions.reduce(sessionReducer, s);
const msg = (m: ServerMsg, now = 0): SessionAction => ({ kind: "msg", msg: m, now });
const started: ServerMsg = {
  type: "call_started", session_id: "s1", role: "client", scenario: "grandchild", voice: "clone",
  customer: { id: "CUST-004217", name: "Kevin", account_mask: "••4217", enrolled: true },
  audio: { sample_rate: 16000, format: "pcm_s16le" }, max_call_s: 240, visitor_as: "Kevin's grandparent",
};

test("intervention, Baseline voice, actions, suspicion and flag times", () => {
  let s = run([{ kind: "request" }, msg(started, 0)]);
  s = run([msg({ type: "alert", level: "caution", reasons: ["x"], suggested_action: "", signals: ["fraud"], citations: [] }, 12_000)], s);
  assert.equal(s.flagT, 12);
  s = run([msg({ type: "intervention", level: "caution", message: "This voice may not really be Kevin.", reason_id: "voice_clone" }, 12_100)], s);
  s = run([msg({ type: "intervention", level: "high", message: "No real bank asks for gift cards.", reason_id: "gift_cards" }, 20_000)], s);
  assert.deepEqual(s.interventions.map((i) => [i.level, i.reason_id, i.t]), [["caution", "voice_clone", 12.1], ["high", "gift_cards", 20]]);
  s = run([msg({ type: "baseline_audio_start", reason_id: "gift_cards", text: "..." }, 20_100)], s);
  assert.equal(s.baselineSpeaking, true);
  s = run([msg({ type: "action", kind: "family_alert", message: "Text sent" }), msg({ type: "action", kind: "bank_hold", message: "Held" }), msg({ type: "action", kind: "bank_hold", message: "Held" })], s);
  assert.deepEqual(s.actions.map((a) => a.kind), ["family_alert", "bank_hold"]);
  s = run([msg({ type: "baseline_audio_end", reason_id: "gift_cards" })], s);
  assert.equal(s.baselineSpeaking, false);
  s = run([{ kind: "suspect", now: 41_000 }, { kind: "suspect", now: 50_000 }], s);
  assert.equal(s.suspectT, 41); // once
  s = run([msg({ type: "suspect_ack", t: 40.8 })], s);
  assert.equal(s.suspectT, 40.8); // server time wins
  s = run([msg({ type: "call_ended", reason: "hangup", report_id: "r1", reveal: { role: "client", scenario: "grandchild", persona_label: "Clone", voice: "clone", tts: "elevenlabs", you_vs_baseline: { visitor_flag_t: 40.8, baseline_flag_t: 11.9 } } }, 60_000)], s);
  assert.equal(s.phase, "ended");
  assert.equal(s.flagT, 12); // the client-side time is kept
});

test("client signals become 'You' notes: secrets flag, compliance watches", () => {
  const lines = [
    { type: "transcript" as const, utterance_id: 1000, t_start: 5, t_end: 5, text: "Okay, the code is 4 8 2 9 1 7" },
    { type: "transcript" as const, utterance_id: 1001, t_start: 9, t_end: 9, text: "Which store should I go to?" },
  ];
  const sig = (uid: number, score: number, reason: string, quote: string) => ({ type: "signal" as const, utterance_id: uid, signal: "client" as const, score, confidence: 0.85, reason, details: { quote }, latency_ms: 0 });
  const notes = buildNotes(lines, [sig(1000, 0.9, "About to read out a one-time code", "the code is"), sig(1001, 0.65, "Agreeing to pay with gift cards", "Which store")], []);
  assert.deepEqual(notes.map((n) => [n.kind, n.tier, n.utterance_id]), [["client", "flag", 1000], ["client", "watch", 1001]]);
  assert.deepEqual(notes[0].span, [6, 17]);
});

test("backend report with interventions, actions and suspicion replays", () => {
  const raw = {
    id: "r9", ended_reason: "hangup",
    meta: { role: "client", scenario: "grandchild", voice: "clone", tts: "elevenlabs", persona: { label: "Clone of Kevin", summary: "A scammer used a cloned voice." },
      customer: { id: "CUST-004217", name: "Kevin", account_mask: "••4217", enrolled: true } },
    durations: { call_s: 50 },
    transcript: [{ utterance_id: 0, speaker: "ai", analyzed: true, text: "Grandma? It's me, Kevin.", t_start: 0.5, t_end: 4 }],
    signals: [], trust: [],
    alerts: [{ level: "high", reasons: ["x"], suggested_action: "", signals: ["spoof", "speaker"], citations: [], t: 5.6 }],
    interventions: [{ t: 5.6, level: "high", reason_id: "voice_clone", message: "This voice may not really be Kevin.", spoken: true }],
    actions: [{ t: 5.6, kind: "family_alert", message: "Text sent" }, { t: 5.6, kind: "bank_hold", message: "Held" }],
    suspicion: { t: 26.1 },
    you_vs_baseline: { visitor_flag_t: 26.1, baseline_flag_t: 5.6 },
  };
  const s = replay(eventsFromBackend("r9", raw));
  assert.equal(s.call?.role, "client");
  assert.equal(s.interventions.length, 1);
  assert.equal(s.actions.length, 2);
  assert.equal(s.suspectT, 26.1);
  assert.equal(s.flagT, 5.6);
  assert.equal(s.ended?.reveal.summary, "A scammer used a cloned voice.");
});
