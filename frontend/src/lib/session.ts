// Call session state machine: lobby -> requesting -> queued -> live -> ended (or error).
// Pure reducer, no DOM: unit-tested under node --test (tests/session.test.ts).
import { EMPTY_EVIDENCE, mergeEvidence, type EvidenceState } from "../analysis.ts";
import type { AlertEvent, SignalEvent, TranscriptEvent } from "../types.ts";
import type { MsgOf, ServerMsg, Speaker } from "./contract.ts";

export type Phase = "lobby" | "requesting" | "queued" | "live" | "ended" | "error";

export interface Line extends TranscriptEvent {
  speaker: Speaker;
  analyzed: boolean;
}

export interface SessionState {
  phase: Phase;
  queue: { position: number; queue_length: number; eta_s: number } | null;
  call: MsgOf<"call_started"> | null;
  /** client clock (ms) when call_started arrived */
  startedAt: number | null;
  endedAt: number | null;
  lines: Line[];
  signals: SignalEvent[];
  evidence: EvidenceState;
  trust: number;
  trustHistory: { t: number; score: number }[];
  alert: AlertEvent | null;
  /** highest alert level seen in this call, and the alert that set it */
  peak: AlertEvent["level"];
  peakAlert: AlertEvent | null;
  speaking: Record<Speaker, boolean>;
  warning: { message: string; seconds_left: number; at: number } | null;
  ended: MsgOf<"call_ended"> | null;
  error: string | null;
}

export const INITIAL: SessionState = {
  phase: "lobby",
  queue: null,
  call: null,
  startedAt: null,
  endedAt: null,
  lines: [],
  signals: [],
  evidence: EMPTY_EVIDENCE,
  trust: 100,
  trustHistory: [],
  alert: null,
  peak: "none",
  peakAlert: null,
  speaking: { ai: false, visitor: false },
  warning: null,
  ended: null,
  error: null,
};

export type SessionAction =
  | { kind: "request" }
  | { kind: "msg"; msg: ServerMsg; now: number }
  | { kind: "cancel" }
  | { kind: "fail"; message: string }
  | { kind: "closed"; now: number }
  | { kind: "reset" };

const LEVEL_RANK = { none: 0, caution: 1, high: 2 } as const;

/** Seconds since the call started, for the timeline axis. */
export function elapsed(s: SessionState, now: number): number {
  if (s.startedAt == null) return 0;
  return Math.max(0, ((s.endedAt ?? now) - s.startedAt) / 1000);
}

function onMsg(s: SessionState, msg: ServerMsg, now: number): SessionState {
  // Anything arriving after the visitor cancelled or the call ended is stale.
  if (s.phase === "lobby" || s.phase === "error") return s;
  if (s.phase === "ended" && msg.type !== "call_ended") return s;
  switch (msg.type) {
    case "queue":
      if (s.phase !== "requesting" && s.phase !== "queued") return s;
      return { ...s, phase: "queued", queue: { position: msg.position, queue_length: msg.queue_length, eta_s: msg.eta_s } };
    case "call_started":
      return { ...INITIAL, phase: "live", call: msg, startedAt: now };
    case "error":
      return { ...s, phase: s.phase === "live" ? s.phase : "error", error: msg.message };
    case "call_ended":
      if (s.phase === "ended" && s.ended) return s;
      return { ...s, phase: "ended", ended: msg, endedAt: s.endedAt ?? now, speaking: { ai: false, visitor: false } };
  }
  if (s.phase !== "live") return s;
  switch (msg.type) {
    case "speaking":
      return { ...s, speaking: { ...s.speaking, [msg.who]: msg.state === "start" } };
    case "transcript": {
      const line: Line = {
        type: "transcript",
        utterance_id: msg.utterance_id,
        t_start: msg.t_start,
        t_end: msg.t_end,
        text: msg.text,
        speaker: msg.speaker,
        analyzed: msg.analyzed,
      };
      const exists = s.lines.some((l) => l.utterance_id === line.utterance_id);
      const lines = exists ? s.lines.map((l) => (l.utterance_id === line.utterance_id ? line : l)) : [...s.lines, line];
      return { ...s, lines };
    }
    case "signal": {
      const ev: SignalEvent = {
        type: "signal",
        utterance_id: msg.utterance_id,
        signal: msg.signal,
        score: msg.score,
        confidence: msg.confidence,
        reason: msg.reason,
        details: msg.details ?? {},
        latency_ms: 0,
      };
      return {
        ...s,
        signals: [...s.signals, ev],
        evidence: ev.signal === "fraud" ? mergeEvidence(s.evidence, ev, s.lines) : s.evidence,
      };
    }
    case "trust":
      return { ...s, trust: msg.score, trustHistory: [...s.trustHistory, { t: elapsed(s, now), score: msg.score }] };
    case "alert": {
      const alert: AlertEvent = { ...msg, type: "alert" };
      const up = LEVEL_RANK[msg.level] >= LEVEL_RANK[s.peak] && msg.level !== "none";
      return { ...s, alert, peak: up ? msg.level : s.peak, peakAlert: up ? alert : s.peakAlert };
    }
    case "warning":
      return { ...s, warning: { message: msg.message, seconds_left: msg.seconds_left, at: now } };
    default:
      // ai_level / stop_audio are routed outside React state (per-frame values).
      return s;
  }
}

export function sessionReducer(s: SessionState, a: SessionAction): SessionState {
  switch (a.kind) {
    case "request":
      return { ...INITIAL, phase: "requesting" };
    case "cancel":
    case "reset":
      return INITIAL;
    case "fail":
      return { ...s, phase: s.phase === "live" ? "ended" : "error", error: a.message, endedAt: s.endedAt ?? (s.phase === "live" ? Date.now() : null) };
    case "closed":
      if (s.phase === "live") return { ...s, phase: "ended", endedAt: a.now, error: s.error ?? "The connection dropped." };
      if (s.phase === "requesting" || s.phase === "queued") return { ...s, phase: "error", error: "Lost the connection while waiting. Try again." };
      return s;
    case "msg":
      return onMsg(s, a.msg, a.now);
  }
}
