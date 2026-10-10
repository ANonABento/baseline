// Call reports: every call is recorded client-side as its event log (so the report page
// works in mock mode and if the backend report endpoint is down), and backend reports are
// normalized into the same event log, then replayed through the session reducer.
import type { MsgOf, ServerMsg } from "./contract.ts";
import { INITIAL, sessionReducer, type SessionState } from "./session.ts";

export interface Recorded {
  msg: ServerMsg;
  /** ms since the first recorded event */
  at: number;
}

export interface StoredReport {
  id: string;
  savedAt: number;
  mock: boolean;
  events: Recorded[];
}

const PREFIX = "baseline.report.";
const INDEX = "baseline.reports";

export function replay(events: Recorded[]): SessionState {
  let s: SessionState = { ...INITIAL, phase: "requesting" };
  for (const e of events) s = sessionReducer(s, { kind: "msg", msg: e.msg, now: e.at });
  if (s.phase === "live") s = { ...s, phase: "ended", endedAt: events.at(-1)?.at ?? s.startedAt };
  return s;
}

export function saveReport(r: StoredReport) {
  try {
    localStorage.setItem(PREFIX + r.id, JSON.stringify(r));
    const idx = listReports().filter((x) => x.id !== r.id);
    idx.unshift(summarize(r));
    localStorage.setItem(INDEX, JSON.stringify(idx.slice(0, 20)));
  } catch {
    /* storage full or blocked: the backend copy still exists */
  }
}

export function loadLocal(id: string): StoredReport | null {
  try {
    const raw = localStorage.getItem(PREFIX + id);
    return raw ? (JSON.parse(raw) as StoredReport) : null;
  } catch {
    return null;
  }
}

export interface ReportSummary {
  id: string;
  savedAt: number;
  scenario: string;
  role: string;
  peak: string;
  duration: number;
}

export function summarize(r: StoredReport): ReportSummary {
  const s = replay(r.events);
  return {
    id: r.id,
    savedAt: r.savedAt,
    scenario: s.ended?.reveal.scenario ?? s.call?.scenario ?? "",
    role: s.ended?.reveal.role ?? s.call?.role ?? "",
    peak: s.peak,
    duration: s.startedAt != null && s.endedAt != null ? (s.endedAt - s.startedAt) / 1000 : 0,
  };
}

export function listReports(): ReportSummary[] {
  try {
    return JSON.parse(localStorage.getItem(INDEX) ?? "[]") as ReportSummary[];
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------- backend report normalization

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {});
const arr = (v: unknown): Obj[] => (Array.isArray(v) ? (v.filter((x) => x && typeof x === "object") as Obj[]) : []);
const s = (v: unknown, d = ""): string => (typeof v === "string" ? v : d);
const n = (v: unknown, d = 0): number => (typeof v === "number" && isFinite(v) ? v : d);

/**
 * Backend report -> event log. Accepts either `{events:[...]}` or the documented summary
 * shape (session meta, transcript, signals, alerts, verdict, evidence); unknown fields are
 * ignored so a richer report never breaks the page.
 */
export function eventsFromBackend(id: string, raw: unknown): Recorded[] {
  const r = obj(raw);
  if (Array.isArray(r.events)) {
    return arr(r.events).map((e, i) => ({ msg: e as unknown as ServerMsg, at: n(e.at, i) }));
  }
  // live backend: {meta:{role, scenario, voice, tts, persona:{label}, customer}, durations:{call_s}, ended_reason, ...}
  const sess = obj(r.session ?? r.meta);
  const persona = obj(sess.persona);
  const reveal = { persona_label: persona.label, tts: sess.tts, ...obj(r.reveal ?? sess.reveal) } as Obj;
  const callS = n(obj(r.durations).call_s, n(sess.duration_s, NaN));
  const cust = obj(sess.customer ?? r.customer);
  const out: Recorded[] = [];
  const t0 = 0;
  const started: MsgOf<"call_started"> = {
    type: "call_started",
    session_id: s(sess.session_id ?? sess.id, id),
    role: (s(sess.role ?? reveal.role, "agent") as "agent" | "scammer"),
    scenario: s(sess.scenario ?? reveal.scenario),
    voice: s(sess.voice ?? reveal.voice),
    customer: { id: s(cust.id), name: s(cust.name, "Unknown caller"), account_mask: s(cust.account_mask), enrolled: !!cust.enrolled },
    audio: { sample_rate: 16000, format: "pcm_s16le" },
    max_call_s: n(sess.max_call_s, 0),
  };
  out.push({ msg: started, at: t0 });
  type Timed = { t: number; msg: ServerMsg };
  const timed: Timed[] = [];
  const tOf = new Map<number, number>();
  for (const l of arr(r.transcript)) {
    const uid = n(l.utterance_id);
    tOf.set(uid, n(l.t_end));
    timed.push({
      t: n(l.t_end),
      msg: { type: "transcript", utterance_id: uid, t_start: n(l.t_start), t_end: n(l.t_end), text: s(l.text), speaker: s(l.speaker) === "visitor" ? "visitor" : "ai", analyzed: l.analyzed !== false },
    });
  }
  for (const g of arr(r.signals)) {
    const uid = n(g.utterance_id);
    timed.push({
      t: n(g.t, (tOf.get(uid) ?? 0) + 0.001),
      msg: { type: "signal", utterance_id: uid, signal: s(g.signal) as "fraud", score: n(g.score), confidence: n(g.confidence), reason: s(g.reason), details: obj(g.details) },
    });
  }
  for (const a of arr(r.alerts)) {
    const uid = n(a.utterance_id, -1);
    timed.push({
      t: n(a.t, uid >= 0 ? (tOf.get(uid) ?? 0) + 0.002 : Infinity),
      msg: {
        type: "alert",
        level: (s(a.level, "none") as "none"),
        reasons: (a.reasons as string[]) ?? [],
        suggested_action: s(a.suggested_action),
        signals: (a.signals as string[]) ?? [],
        citations: (a.citations as never[]) ?? [],
      },
    });
  }
  timed.sort((a, b) => a.t - b.t);
  const last = Math.max(0, ...timed.filter((x) => isFinite(x.t)).map((x) => x.t));
  for (const x of timed) out.push({ msg: x.msg, at: t0 + (isFinite(x.t) ? x.t : last) * 1000 });
  out.push({
    msg: {
      type: "call_ended",
      reason: s(r.ended_reason ?? r.reason ?? sess.end_reason, "ended"),
      report_id: id,
      reveal: {
        role: (s(reveal.role ?? sess.role, "agent") as "agent"),
        scenario: s(reveal.scenario ?? sess.scenario),
        persona_label: s(reveal.persona_label),
        voice: s(reveal.voice ?? sess.voice),
        tts: s(reveal.tts),
      },
    },
    at: t0 + (isFinite(callS) ? Math.max(callS, last) : last) * 1000,
  });
  return out;
}
