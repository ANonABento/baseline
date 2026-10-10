import { test } from "node:test";
import assert from "node:assert/strict";
import { EMPTY_EVIDENCE, mergeEvidence } from "../src/analysis.ts";
import { audioTier, buildNotes, findSpan, segmentText, spikesFromNotes, verdictOf } from "../src/lib/notes.ts";
import type { AlertEvent, SignalEvent, SignalName, TranscriptEvent } from "../src/types.ts";

const tr = (id: number, t0: number, t1: number, text: string): TranscriptEvent => ({ type: "transcript", utterance_id: id, t_start: t0, t_end: t1, text });
const sig = (signal: SignalName, id: number, score: number, confidence = 0.8, details: Record<string, unknown> = {}): SignalEvent => ({
  type: "signal", utterance_id: id, signal, score, confidence, reason: `${signal} r${id}`, details, latency_ms: 0,
});
const lines = [
  tr(1, 0, 4, "Hi, this is Margaret Chen."),
  tr(2, 5, 9, "I got a new phone, so I need to update the number on file, and the email too."),
  tr(3, 10, 15, "Once that's done I need to wire nine thousand dollars to a new account. Today, it can't wait."),
];
const pattern = (id: string, uid: number, quote: string, severity: unknown, extra: Record<string, unknown> = {}) => ({
  id, name: id, severity, quote, utterance_id: uid, source: { name: "FTC", url: "https://ftc.gov/x" }, suggested_agent_action: `do ${id}`, ...extra,
});

test("findSpan: exact, case/curly-quote insensitive, prefix fallback, miss", () => {
  assert.deepEqual(findSpan("Today, it can't wait.", "it can’t wait"), [7, 20]);
  assert.deepEqual(findSpan("WIRE nine thousand dollars", "wire nine"), [0, 9]);
  assert.deepEqual(findSpan("I need to wire nine thousand dollars to a new account", "wire nine thousand dollars to my nephew"), [10, 39]);
  assert.equal(findSpan("Hello there", "completely different"), null);
  assert.equal(findSpan("Hello", ""), null);
});

test("audio tiers: onset only, prosody capped one tier lower, low confidence ignored", () => {
  assert.equal(audioTier(sig("spoof", 1, 0.6)), "flag");
  assert.equal(audioTier(sig("spoof", 1, 0.3)), "watch");
  assert.equal(audioTier(sig("spoof", 1, 0.1)), null);
  assert.equal(audioTier(sig("prosody", 1, 0.6)), "watch");
  assert.equal(audioTier(sig("prosody", 1, 0.3)), "noted");
  assert.equal(audioTier(sig("spoof", 1, 0.9, 0.1)), null);
});

test("buildNotes: fraud patterns anchor to quoted spans; audio notes attach where they first fired", () => {
  let ev = mergeEvidence(EMPTY_EVIDENCE, sig("fraud", 2, 0.45, 0.85, { patterns: [pattern("contact", 2, "update the number on file", 0.45)] }), lines);
  ev = mergeEvidence(ev, sig("fraud", 3, 0.9, 0.85, { patterns: [pattern("ato", 3, "wire nine thousand dollars", 0.9, { say_this: "I'll call you back." })] }), lines);
  const signals = [sig("spoof", 1, 0.3), sig("spoof", 2, 0.64), sig("spoof", 3, 0.78), sig("speaker", 3, 0.6), sig("speaker", 1, 0.1)];
  const notes = buildNotes(lines, signals, ev.items);

  const contact = notes.find((n) => n.id === "fraud:contact")!;
  assert.equal(contact.tier, "watch"); // numeric severity 0.45 -> medium
  assert.equal(contact.utterance_id, 2);
  const at = lines[1].text.indexOf("update the number on file");
  assert.deepEqual(contact.span, [at, at + "update the number on file".length]);
  assert.equal(contact.sourceUrl, "https://ftc.gov/x");
  const ato = notes.find((n) => n.id === "fraud:ato")!;
  assert.equal(ato.tier, "flag");
  assert.equal(ato.sayThis, "I'll call you back.");

  // spoof: watch at line 1, flag at line 2, nothing again at 3 (onset rule)
  const spoof = notes.filter((n) => n.kind === "spoof").map((n) => [n.utterance_id, n.tier]);
  assert.deepEqual(spoof, [[1, "watch"], [2, "flag"]]);
  // speaker fires first at line 3
  assert.deepEqual(notes.filter((n) => n.kind === "speaker").map((n) => [n.utterance_id, n.tier]), [[3, "flag"]]);
  // sorted by line, flags first within a line
  assert.deepEqual(notes.map((n) => n.utterance_id), [...notes.map((n) => n.utterance_id)].sort((a, b) => a - b));
  const line3 = notes.filter((n) => n.utterance_id === 3);
  assert.equal(line3[0].tier, "flag");
});

test("fraud without pattern evidence falls back to an onset note", () => {
  const notes = buildNotes(lines, [sig("fraud", 2, 0.2), sig("fraud", 3, 0.7), sig("fraud", 3, 0.8)], []);
  assert.deepEqual(notes.map((n) => [n.kind, n.utterance_id, n.tier]), [["fraud", 3, "flag"]]);
});

test("segmentText splits overlapping spans and keeps the worst tier", () => {
  const text = "wire nine thousand dollars today";
  const notes = [
    { id: "a", utterance_id: 1, tier: "watch" as const, kind: "fraud" as const, title: "", body: "", quote: "", span: [0, 18] as [number, number] },
    { id: "b", utterance_id: 1, tier: "flag" as const, kind: "fraud" as const, title: "", body: "", quote: "", span: [5, 26] as [number, number] },
  ];
  const segs = segmentText(text, notes);
  assert.equal(segs.map((s) => s.text).join(""), text);
  assert.deepEqual(segs.map((s) => [s.text, s.tier, s.noteIds]), [
    ["wire ", "watch", ["a"]],
    ["nine thousand", "flag", ["a", "b"]],
    [" dollars", "flag", ["b"]],
    [" today", null, []],
  ]);
});

test("spikes sit at the middle of their line on the axis", () => {
  const notes = buildNotes(lines, [sig("spoof", 2, 0.7)], []);
  const [s] = spikesFromNotes(notes, lines, 70);
  assert.equal(s.x, 7 / 70);
  assert.equal(s.tier, "flag");
});

test("verdict: level from alert, agreeing signals, best say-this line", () => {
  const ev = mergeEvidence(EMPTY_EVIDENCE, sig("fraud", 3, 0.9, 0.85, {
    patterns: [pattern("urgency", 3, "Today", "low", { say_this: "low line" }), pattern("ato", 3, "wire", "high", { say_this: "high line" })],
  }), lines);
  const alert: AlertEvent = { type: "alert", level: "high", reasons: [], suggested_action: "fallback", signals: ["spoof", "fraud", "spoof"], citations: [] };
  const v = verdictOf(alert, [], ev.items);
  assert.equal(v.level, "alert");
  assert.equal(v.agreeing, 2);
  assert.equal(v.sayThis, "high line");
  assert.equal(verdictOf(null, [], ev.items).sayThis, null);
  assert.equal(verdictOf({ ...alert, level: "caution" }, [], []).sayThis, "fallback");
});
