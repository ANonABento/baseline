import { useCallback, useEffect, useReducer, useRef } from "react";
import { PcmPlayer, playChime } from "./audio";
import { openSession, type Transport } from "./client";
import type { ServerMsg, SessionRequest } from "./contract";
import { saveReport, type Recorded } from "./reports";
import { INITIAL, sessionReducer } from "./session";

/** Owns the transport, the AI-voice player and the call recorder for one visitor. */
export function useSession() {
  const [state, dispatch] = useReducer(sessionReducer, INITIAL);
  const transport = useRef<Transport | null>(null);
  const player = useRef<PcmPlayer | null>(null);
  /** Baseline's own voice: a separate player so ducking / barge-in on the caller never cuts it */
  const baseline = useRef<PcmPlayer | null>(null);
  const inBaseline = useRef(false);
  const level = useRef({ v: 0, at: 0, fromServer: 0 });
  const log = useRef<Recorded[]>([]);
  const t0 = useRef(0);
  const mock = useRef(false);
  const hangTimer = useRef(0);

  const record = (msg: ServerMsg) => {
    if (msg.type === "ai_level" || (msg as { type: string }).type === "pong") return;
    if (!log.current.length) t0.current = performance.now();
    log.current.push({ msg, at: performance.now() - t0.current });
  };

  const onMsg = useCallback((msg: ServerMsg) => {
    record(msg);
    const now = performance.now();
    switch (msg.type) {
      case "ai_level":
        level.current = { v: msg.rms, at: now, fromServer: now };
        return;
      case "stop_audio":
        player.current?.stop();
        level.current.v = 0;
        return;
      case "call_started":
        player.current?.setSampleRate(msg.audio?.sample_rate ?? 16000);
        baseline.current?.setSampleRate(msg.audio?.sample_rate ?? 16000);
        inBaseline.current = false;
        break;
      case "intervention": {
        const ctx = player.current?.context;
        if (ctx) {
          try {
            playChime(ctx);
          } catch {
            /* no audio output */
          }
        }
        break;
      }
      case "baseline_audio_start":
        // duck the caller: fade out whatever of the AI is still queued, Baseline speaks alone
        inBaseline.current = true;
        player.current?.fadeStop(160);
        level.current.v = 0;
        break;
      case "baseline_audio_end":
        inBaseline.current = false;
        break;
      case "call_ended":
        window.clearTimeout(hangTimer.current);
        player.current?.stop();
        baseline.current?.stop();
        inBaseline.current = false;
        saveReport({ id: msg.report_id || `local-${Date.now().toString(36)}`, savedAt: Date.now(), mock: mock.current, events: [...log.current] });
        break;
    }
    dispatch({ kind: "msg", msg, now: Date.now() });
  }, []);

  const onAudio = useCallback((pcm: ArrayBuffer) => {
    if (inBaseline.current) {
      baseline.current?.push(pcm);
      return;
    }
    const p = player.current;
    if (!p) return;
    const r = p.push(pcm);
    const now = performance.now();
    // animate from the audio itself if the server isn't sending ai_level
    if (now - level.current.fromServer > 500) level.current = { ...level.current, v: Math.min(1, r * 4), at: now };
  }, []);

  const onClose = useCallback(() => {
    transport.current = null;
    dispatch({ kind: "closed", now: Date.now() });
  }, []);

  const join = useCallback(
    async (req: SessionRequest) => {
      dispatch({ kind: "request" });
      log.current = [];
      try {
        player.current ??= new PcmPlayer(16000);
        baseline.current ??= new PcmPlayer(16000);
        await Promise.all([player.current.resume(), baseline.current.resume()]);
      } catch {
        /* no audio output: the call still works visually */
      }
      try {
        const s = await openSession(req, { onMsg, onAudio, onClose });
        mock.current = s.mock;
        transport.current = s.transport;
      } catch (e) {
        dispatch({ kind: "fail", message: `Couldn't start a call: ${(e as Error).message}` });
      }
    },
    [onMsg, onAudio, onClose],
  );

  const cancel = useCallback(() => {
    transport.current?.close();
    transport.current = null;
    player.current?.stop();
    dispatch({ kind: "cancel" });
  }, []);

  const hangup = useCallback(() => {
    const t = transport.current;
    if (!t) return dispatch({ kind: "closed", now: Date.now() });
    t.send({ type: "hangup" });
    // if the server never confirms, end locally
    hangTimer.current = window.setTimeout(() => {
      transport.current?.close();
      dispatch({ kind: "closed", now: Date.now() });
    }, 4000);
  }, []);

  const sendText = useCallback((text: string) => transport.current?.send({ type: "text", text }), []);
  /** "This feels like a scam": recorded once, locally right away and on the server for the report */
  const suspect = useCallback(() => {
    dispatch({ kind: "suspect", now: Date.now() });
    transport.current?.send({ type: "suspect" });
  }, []);
  /** push-to-talk edges: the server closes the turn on "up" instead of waiting for silence */
  const ptt = useCallback((state: "down" | "up") => transport.current?.send({ type: "ptt", state }), []);
  const sendPcm = useCallback((pcm: ArrayBuffer) => transport.current?.sendPcm(pcm), []);
  const bargeIn = useCallback(() => {
    player.current?.stop();
    level.current.v = 0;
  }, []);
  const reset = useCallback(() => dispatch({ kind: "reset" }), []);

  /** AI loudness for the caller tile, decaying between updates. */
  const aiLevel = useCallback(() => {
    const { v, at } = level.current;
    return v * Math.exp(-(performance.now() - at) / 220);
  }, []);

  useEffect(
    () => () => {
      transport.current?.close();
      player.current?.close();
      baseline.current?.close();
      window.clearTimeout(hangTimer.current);
    },
    [],
  );

  return { state, join, cancel, hangup, sendText, suspect, sendPcm, ptt, bargeIn, reset, aiLevel, isMock: () => mock.current };
}
