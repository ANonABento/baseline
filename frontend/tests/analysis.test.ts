// Run with `npm test` (node --test, native TypeScript type stripping; Node >= 22.18).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_EVIDENCE,
  buildTimeline,
  lineTriggers,
  mergeEvidence,
  patternsFromSignal,
  toneOf,
} from "../src/analysis.ts";
import type { SignalEvent, SignalName, TranscriptEvent } from "../src/types.ts";

const tr = (id: number, t0: number, t1: number, text: string): TranscriptEvent => ({
  type: "transcript", utterance_id: id, t_start: t0, t_end: t1, text,
});
const sig = (signal: SignalName, id: number, score: number, confidence = 0.8, details: Record<string, unknown> = {}): SignalEvent => ({
  type: "signal", utterance_id: id, signal, score, confidence, reason: `${signal} r${id}`, details, latency_ms: 1,
});

const transcript = [
  tr(1, 0.5, 5.5, "Hi, this is Margaret Chen. I need to update the phone number on my account."),
  tr(2, 6.0, 10.8, "I got a new phone, so please change my phone number and my email too."),
  tr(3, 11.1, 16.0, "Once that's done, I need to wire nine thousand dollars to a new account today."),
  tr(4, 16.4, 19.5, "It's urgent, it has to go out right now."),
];

const contractPattern = (id: string, utterance_id: number, quote: string, severity = "high") => ({
  id, name: id.toUpperCase(), severity, quote, utterance_id, source: `https://x/${id}`, suggested_agent_action: `act ${id}`,
});

test("contract patterns are parsed verbatim", () => {
  const ev = sig("fraud", 3, 0.9, 0.8, { patterns: [contractPattern("wire", 3, "wire nine thousand")], engine: "llm", model: "m1" });
  const [p] = patternsFromSignal(ev);
  assert.deepEqual(p, contractPattern("wire", 3, "wire nine thousand"));
  const st = mergeEvidence(EMPTY_EVIDENCE, ev);
  assert.equal(st.engine, "llm");
  assert.equal(st.model, "m1");
});

test("merge dedupes by id, keeps the latest quote, escalates severity only", () => {
  let st = mergeEvidence(EMPTY_EVIDENCE, sig("fraud", 2, 0.6, 0.8, { patterns: [contractPattern("ato", 2, "change my phone number", "medium")] }));
  st = mergeEvidence(st, sig("fraud", 3, 0.9, 0.8, {
    patterns: [contractPattern("ato", 3, "wire nine thousand dollars", "high"), contractPattern("urgent", 3, "today", "low")],
  }));
  st = mergeEvidence(st, sig("fraud", 4, 0.9, 0.8, { patterns: [contractPattern("ato", 4, "", "low")] }));
  assert.equal(st.items.length, 2);
  const ato = st.items.find((i) => i.id === "ato")!;
  assert.equal(ato.quote, "wire nine thousand dollars"); // empty quote doesn't overwrite
  assert.equal(ato.utterance_id, 3);
  assert.equal(ato.severity, "high"); // never de-escalates
  assert.equal(ato.first_utterance_id, 2);
  assert.equal(ato.updated_utterance_id, 4);
  assert.deepEqual(st.items.map((i) => i.id), ["ato", "urgent"]); // sorted by severity
});

test("absent / foreign details are tolerated", () => {
  assert.deepEqual(patternsFromSignal(sig("fraud", 1, 0, 0, {})), []);
  assert.deepEqual(patternsFromSignal(sig("fraud", 1, 0, 0, { patterns: "nope" })), []);
  assert.deepEqual(patternsFromSignal(sig("fraud", 1, 0, 0, { patterns: [null, 3, {}] })), []);
  assert.deepEqual(patternsFromSignal(sig("spoof", 1, 0.9, 0.9, { patterns: ["x"] })), []);
  assert.equal(mergeEvidence(EMPTY_EVIDENCE, sig("spoof", 1, 0.9)), EMPTY_EVIDENCE);
});

test("legacy id-list details recover quote + utterance from matched phrases", () => {
  const ev = sig("fraud", 4, 0.85, 0.7, {
    method: "keyword",
    patterns: ["ato_contact_change_then_money"],
    matched_phrases: { ato_contact_change_then_money: ["change my phone number", "wire"] },
    citations: [{ pattern_id: "ato_contact_change_then_money", name: "Account takeover", source: "https://ftc.gov" }],
    suggested_action: "Call back on file.",
  });
  const st = mergeEvidence(EMPTY_EVIDENCE, ev, transcript);
  assert.equal(st.engine, "keyword");
  const [p] = st.items;
  assert.equal(p.name, "Account takeover");
  assert.equal(p.utterance_id, 2); // first line containing a hit
  assert.match(p.quote, /change my phone number/);
  assert.equal(p.source, "https://ftc.gov");
  assert.equal(p.suggested_agent_action, "Call back on file.");
  assert.equal(p.severity, "high");
});

test("toneOf matches fusion thresholds", () => {
  assert.equal(toneOf({ score: 0.9, confidence: 0 }), "none");
  assert.equal(toneOf({ score: 0.5, confidence: 0.5 }), "flag");
  assert.equal(toneOf({ score: 0.3, confidence: 0.5 }), "watch");
  assert.equal(toneOf({ score: 0.1, confidence: 0.5 }), "ok");
});

test("lineTriggers: audio signals mark onset only; fraud anchors to quoted line", () => {
  const signals = [sig("spoof", 1, 0.9), sig("spoof", 2, 0.9), sig("spoof", 3, 0.2), sig("spoof", 4, 0.8), sig("speaker", 1, 0.1)];
  const st = mergeEvidence(EMPTY_EVIDENCE, sig("fraud", 3, 0.9, 0.8, { patterns: [contractPattern("wire", 3, "wire")] }));
  const m = lineTriggers(signals, st.items);
  assert.deepEqual(m.get(1)?.map((t) => t.signal), ["spoof"]);
  assert.equal(m.get(2), undefined);
  assert.deepEqual(m.get(3)?.map((t) => [t.signal, t.patternId]), [["fraud", "wire"]]);
  assert.deepEqual(m.get(4)?.map((t) => t.signal), ["spoof"]); // re-fired after dropping
});

test("lineTriggers: fraud onset used when no pattern evidence", () => {
  const m = lineTriggers([sig("fraud", 2, 0.4), sig("fraud", 3, 0.7), sig("fraud", 4, 0.8)], []);
  assert.deepEqual([...m.keys()], [3]);
});

test("buildTimeline maps utterances and markers onto a shared axis", () => {
  const signals = [
    sig("spoof", 1, 0.9),
    sig("speaker", 1, 0.1),
    sig("prosody", 1, 0.5, 0), // confidence 0 -> no marker
    sig("spoof", 9, 0.9), // no transcript yet -> omitted
    sig("fraud", 3, 0.6),
    sig("fraud", 3, 0.9), // latest per (lane, utt) wins
  ];
  const st = mergeEvidence(EMPTY_EVIDENCE, sig("fraud", 3, 0.9, 0.8, { patterns: [contractPattern("wire", 3, "wire")] }));
  const tl = buildTimeline(transcript, signals, st.items);
  assert.equal(tl.duration, 30); // min duration
  assert.equal(tl.segments.length, 4);
  assert.ok(Math.abs(tl.segments[0].x0 - 0.5 / 30) < 1e-9);
  assert.equal(tl.segments[2].tone, "flag");
  assert.deepEqual(tl.markers.map((m) => m.key), ["spoof-1", "speaker-1", "fraud-3"]);
  const fraud = tl.markers.find((m) => m.lane === "fraud")!;
  assert.equal(fraud.score, 0.9);
  assert.deepEqual(fraud.patterns, ["WIRE"]);
  assert.ok(Math.abs(fraud.x - (11.1 + 16.0) / 2 / 30) < 1e-9);
  for (const m of tl.markers) assert.ok(m.x >= 0 && m.x <= 1);
});

test("buildTimeline axis grows with the call", () => {
  const tl = buildTimeline([tr(1, 40, 47.2, "long call")], []);
  assert.equal(tl.duration, 52);
  assert.ok(tl.segments[0].x1 < 1);
  assert.equal(buildTimeline([], []).duration, 30);
});
