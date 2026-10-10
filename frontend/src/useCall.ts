import { useCallback, useEffect, useReducer, useRef } from "react";
import { EMPTY_EVIDENCE, mergeEvidence, type EvidenceState } from "./analysis";
import type { AlertEvent, ServerEvent, SignalEvent, SignalName, TranscriptEvent } from "./types";

export const WS_URL: string = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000/ws/call";
export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Conn = "connecting" | "open" | "closed";
export type Mode = "idle" | "replay" | "mic";
export type Phase = "idle" | "live" | "ended";

export interface CallState {
  conn: Conn;
  mode: Mode;
  /** idle = no call yet, live = streaming, ended = finished call still on screen */
  phase: Phase;
  clip: string | null;
  /** Date.now() when the current call started */
  startedAt: number | null;
  endedAt: number | null;
  transcript: TranscriptEvent[];
  /** latest event per signal (what the signal cards show) */
  signals: Partial<Record<SignalName, SignalEvent>>;
  /** every signal event of the call (timeline + transcript triggers) */
  signalLog: SignalEvent[];
  evidence: EvidenceState;
  trust: number;
  trustHistory: number[];
  alert: AlertEvent | null;
  lastStatus: string;
  /** backend's "connected" status message, e.g. "stt=stub llm=nebius" */
  backendInfo: string;
  error: string | null;
}

const initial: CallState = {
  conn: "connecting",
  mode: "idle",
  phase: "idle",
  clip: null,
  startedAt: null,
  endedAt: null,
  transcript: [],
  signals: {},
  signalLog: [],
  evidence: EMPTY_EVIDENCE,
  trust: 100,
  trustHistory: [100],
  alert: null,
  lastStatus: "",
  backendInfo: "",
  error: null,
};

type Action =
  | { kind: "conn"; conn: Conn }
  | { kind: "event"; ev: ServerEvent }
  | { kind: "reset"; mode: Mode; clip?: string | null };

function freshCall(s: CallState, mode: Mode, clip: string | null): CallState {
  return { ...initial, conn: s.conn, backendInfo: s.backendInfo, mode, clip, phase: "live", startedAt: Date.now() };
}

export function reducer(s: CallState, a: Action): CallState {
  switch (a.kind) {
    case "conn":
      // a dropped socket ends whatever call was streaming
      if (a.conn === "closed" && s.phase === "live") return { ...s, conn: a.conn, mode: "idle", phase: "ended", endedAt: Date.now() };
      return { ...s, conn: a.conn };
    case "reset":
      return freshCall(s, a.mode, a.clip ?? null);
    case "event": {
      const ev = a.ev;
      switch (ev.type) {
        case "transcript":
          if (s.transcript.some((t) => t.utterance_id === ev.utterance_id)) {
            return { ...s, transcript: s.transcript.map((t) => (t.utterance_id === ev.utterance_id ? ev : t)) };
          }
          return { ...s, transcript: [...s.transcript, ev] };
        case "signal":
          return {
            ...s,
            signals: { ...s.signals, [ev.signal]: ev },
            signalLog: [...s.signalLog, ev],
            evidence: ev.signal === "fraud" ? mergeEvidence(s.evidence, ev, s.transcript) : s.evidence,
          };
        case "trust":
          return { ...s, trust: ev.score, trustHistory: [...s.trustHistory, ev.score].slice(-60) };
        case "alert":
          return { ...s, alert: ev };
        case "status":
          switch (ev.state) {
            case "replay_started":
              return { ...freshCall(s, "replay", ev.clip), lastStatus: ev.state };
            case "call_started":
              return s.phase === "live" && s.mode === "mic" ? { ...s, lastStatus: ev.state } : { ...freshCall(s, "mic", null), lastStatus: ev.state };
            case "replay_finished":
            case "call_ended":
              return { ...s, mode: "idle", phase: s.phase === "idle" ? "idle" : "ended", endedAt: s.endedAt ?? Date.now(), lastStatus: ev.state };
            case "connected":
              return { ...s, backendInfo: ev.message, error: null, lastStatus: ev.state };
            case "error":
              return { ...s, error: ev.message, lastStatus: ev.state };
            default:
              return { ...s, lastStatus: ev.state };
          }
      }
    }
  }
  return s;
}

export function useCall() {
  const [state, dispatch] = useReducer(reducer, initial);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let retry: number | undefined;
    const connect = () => {
      dispatch({ kind: "conn", conn: "connecting" });
      const ws = new WebSocket(WS_URL);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;
      ws.onopen = () => dispatch({ kind: "conn", conn: "open" });
      ws.onmessage = (m) => {
        if (typeof m.data !== "string") return;
        try {
          dispatch({ kind: "event", ev: JSON.parse(m.data) as ServerEvent });
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        if (wsRef.current !== ws) return;
        dispatch({ kind: "conn", conn: "closed" });
        if (!closed) retry = window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(retry);
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close();
    };
  }, []);

  const send = useCallback((msg: object | ArrayBuffer) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(msg instanceof ArrayBuffer ? msg : JSON.stringify(msg));
    return true;
  }, []);

  const replay = useCallback((clip: string) => send({ type: "replay", clip }), [send]);
  const startMicCall = useCallback(() => {
    dispatch({ kind: "reset", mode: "mic" });
    return send({ type: "start", source: "mic" });
  }, [send]);
  const stop = useCallback(() => send({ type: "stop" }), [send]);
  const sendAudio = useCallback((pcm: ArrayBuffer) => send(pcm), [send]);

  return { state, replay, startMicCall, stop, sendAudio };
}
