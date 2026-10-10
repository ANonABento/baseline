import { useCallback, useEffect, useReducer, useRef } from "react";
import type { AlertEvent, ServerEvent, SignalEvent, SignalName, TranscriptEvent } from "./types";

export const WS_URL: string = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000/ws/call";
export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Conn = "connecting" | "open" | "closed";
export type Mode = "idle" | "replay" | "mic";

export interface CallState {
  conn: Conn;
  mode: Mode;
  clip: string | null;
  transcript: TranscriptEvent[];
  signals: Partial<Record<SignalName, SignalEvent>>;
  trust: number;
  trustHistory: number[];
  alert: AlertEvent | null;
  lastStatus: string;
  error: string | null;
}

const initial: CallState = {
  conn: "connecting",
  mode: "idle",
  clip: null,
  transcript: [],
  signals: {},
  trust: 100,
  trustHistory: [100],
  alert: null,
  lastStatus: "",
  error: null,
};

type Action =
  | { kind: "conn"; conn: Conn }
  | { kind: "event"; ev: ServerEvent }
  | { kind: "reset"; mode: Mode; clip?: string | null };

function freshCall(s: CallState, mode: Mode, clip: string | null): CallState {
  return { ...initial, conn: s.conn, mode, clip };
}

function reducer(s: CallState, a: Action): CallState {
  switch (a.kind) {
    case "conn":
      return { ...s, conn: a.conn };
    case "reset":
      return freshCall(s, a.mode, a.clip ?? null);
    case "event": {
      const ev = a.ev;
      switch (ev.type) {
        case "transcript":
          return { ...s, transcript: [...s.transcript, ev] };
        case "signal":
          return { ...s, signals: { ...s.signals, [ev.signal]: ev } };
        case "trust":
          return { ...s, trust: ev.score, trustHistory: [...s.trustHistory, ev.score].slice(-60) };
        case "alert":
          return { ...s, alert: ev };
        case "status":
          if (ev.state === "replay_started") return { ...freshCall(s, "replay", ev.clip), lastStatus: ev.state };
          if (ev.state === "replay_finished" || ev.state === "call_ended") return { ...s, mode: "idle", lastStatus: ev.state };
          if (ev.state === "error") return { ...s, error: ev.message, lastStatus: ev.state };
          return { ...s, lastStatus: ev.state };
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
        dispatch({ kind: "conn", conn: "closed" });
        if (!closed) retry = window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(retry);
      wsRef.current?.close();
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
