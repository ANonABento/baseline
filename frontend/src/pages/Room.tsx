import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fmtTime } from "../analysis";
import { Baseline } from "../components/Baseline";
import { Mark, RenderToggle } from "../components/Chrome";
import { Transcript } from "../components/Transcript";
import { Viewport } from "../components/Viewport";
import { currentCamera } from "../lib/media";
import { buildNotes, spikesFromNotes, TIER_GLYPH, verdictOf, type Note } from "../lib/notes";
import { linkTo, navigate } from "../lib/prefs";
import { elapsed, type SessionState } from "../lib/session";
import { micErrorMessage, startMic, type MicHandle } from "../mic";
import { SCENARIO_LABEL } from "./Lobby";

interface Props {
  state: SessionState;
  aiLevel: () => number;
  onHangup: () => void;
  onText: (t: string) => void;
  onPcm: (pcm: ArrayBuffer) => void;
  onBargeIn: () => void;
  onAgain: () => void;
}

const TAIL_MS = 600;

function useNow(active: boolean, ms = 250) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [active, ms]);
  return now;
}

export function VerdictStrip({ v }: { v: ReturnType<typeof verdictOf> }) {
  return (
    <section className={`verdict verdict--${v.level}`} aria-live="assertive">
      <div className="verdict__row">
        <span className="verdict__level">{v.level === "alert" ? "Alert" : v.level === "watching" ? "Watching" : "Clear"}</span>
        <span className="verdict__headline">{v.headline}</span>
        {v.agreeing > 0 && (
          <span className="label verdict__agree">
            {v.agreeing} {v.agreeing === 1 ? "signal" : "signals agree"}
          </span>
        )}
      </div>
      {v.sayThis && (
        <div className="say" key={v.sayThis}>
          <span className="label">Say this</span>
          <p className="say__text">{v.sayThis}</p>
        </div>
      )}
    </section>
  );
}

export function Room({ state, aiLevel, onHangup, onText, onPcm, onBargeIn, onAgain }: Props) {
  const live = state.phase === "live";
  const now = useNow(live);
  const t = elapsed(state, now);
  const call = state.call!;
  const role = state.ended?.reveal.role ?? call.role;
  const notes = useMemo(() => buildNotes(state.lines, state.signals, state.evidence.items), [state.lines, state.signals, state.evidence.items]);
  const verdict = useMemo(() => verdictOf(state.alert, notes, state.evidence.items), [state.alert, notes, state.evidence.items]);
  const [active, setActive] = useState<string | null>(null);
  const [scrollTo, setScrollTo] = useState<{ id: number; n: number } | null>(null);
  const [holding, setHolding] = useState(false);
  const [micErr, setMicErr] = useState<string | null>(null);
  const [text, setText] = useState("");
  const myLevel = useRef(0);
  const [myLevelUi, setMyLevelUi] = useState(0);
  const mic = useRef<MicHandle | null>(null);
  const sendUntil = useRef(0);
  const holdingRef = useRef(false);

  // ---- mic: open once the call is live; only stream while holding (+ a short tail so the VAD closes)
  const ensureMic = useCallback(async () => {
    if (mic.current) return true;
    try {
      mic.current = await startMic(
        (pcm) => {
          if (holdingRef.current || performance.now() < sendUntil.current) onPcm(pcm);
        },
        (lv) => {
          myLevel.current = lv;
          if (holdingRef.current) setMyLevelUi(lv);
        },
      );
      setMicErr(null);
      return true;
    } catch (e) {
      setMicErr(micErrorMessage(e));
      return false;
    }
  }, [onPcm]);

  useEffect(() => {
    if (live) void ensureMic();
    if (!live) {
      mic.current?.stop();
      mic.current = null;
    }
  }, [live, ensureMic]);
  useEffect(() => () => mic.current?.stop(), []);

  const press = useCallback(() => {
    if (!live || holdingRef.current) return;
    holdingRef.current = true;
    setHolding(true);
    onBargeIn();
    void ensureMic();
  }, [live, ensureMic, onBargeIn]);
  const release = useCallback(() => {
    if (!holdingRef.current) return;
    holdingRef.current = false;
    sendUntil.current = performance.now() + TAIL_MS;
    setHolding(false);
    setMyLevelUi(0);
  }, []);

  useEffect(() => {
    const typing = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      return el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable;
    };
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || typing(e) || e.repeat) return;
      e.preventDefault();
      press();
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || typing(e)) return;
      e.preventDefault();
      release();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", release);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", release);
    };
  }, [press, release]);

  // ---- tiles
  const alertChaos = verdict.level === "alert" ? 0.9 : verdict.level === "watching" ? 0.32 : 0;
  const calm = state.trust >= 80 && state.lines.length >= 2 && verdict.level === "clear";
  const resolve = state.phase === "ended" && state.peak === "none" ? 1 : calm ? 0.6 : 0;
  const cust = call.customer;
  const aiIsCaller = role !== "scammer";
  const ident = `${cust.name} · Acct ${cust.account_mask} · ${cust.enrolled ? "Voice enrolled" : "No voiceprint"}`;
  const speakingAi = state.speaking.ai;
  const speakingMe = state.speaking.visitor || holding;
  const video = currentCamera();

  // ---- timeline
  const duration = Math.max(60, Math.ceil((t + 12) / 15) * 15);
  const spikes = useMemo(
    () =>
      spikesFromNotes(notes, state.lines, duration).map((s) => {
        const n = notes.find((x) => x.id === s.noteId) as Note;
        return { id: s.noteId, x: s.x, tier: s.tier, label: `${TIER_GLYPH[n.tier]} ${n.title}` };
      }),
    [notes, state.lines, duration],
  );
  const focusNote = (id: string) => {
    setActive(id);
    const n = notes.find((x) => x.id === id);
    if (n) setScrollTo({ id: n.utterance_id, n: Date.now() });
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const v = text.trim();
    if (!v || !live) return;
    onBargeIn();
    onText(v);
    setText("");
  };

  const left = Math.max(0, (call.max_call_s || 0) - t);
  const who = { ai: "AI", visitor: "You" } as const;

  return (
    <div className="room">
      <header className="room__bar">
        <a href="/" onClick={linkTo("/")} className="wordmark" aria-label="Baseline home">
          <Mark alert={verdict.level === "alert"} />
          <span className="hide-sm">Baseline</span>
        </a>
        <span className="role-badge">{role === "scammer" ? "You: scammer" : "You: bank agent"}</span>
        {live && <span className="live-dot" aria-hidden />}
        <span className="room__timer" aria-label="Call time">
          {fmtTime(t)}
        </span>
        {state.warning && live && <span className="warning hide-sm">{Math.ceil(left)} s left</span>}
        <span style={{ flex: 1 }} />
        <span className="hide-sm">
          <RenderToggle />
        </span>
        <button className="btn btn--danger btn--small" type="button" onClick={onHangup} disabled={!live}>
          Hang up
        </button>
      </header>

      <div className="room__main">
        <div className="room__left">
          <div className={`tile ${speakingAi ? "tile--speaking" : ""} ${aiIsCaller && verdict.level === "alert" ? "tile--alert" : ""}`}>
            <div className="tile__label">
              <span className="label tile__name">{aiIsCaller ? ident : "Dana · First Harbor Bank"}</span>
              <span className="label">{aiIsCaller ? "Caller (AI)" : "Agent (AI)"}</span>
            </div>
            <Viewport source="head" level={aiLevel} chaos={aiIsCaller ? alertChaos : 0} resolve={aiIsCaller ? resolve : 0.4} drift label="The AI caller" />
            <div className="tile__state">{speakingAi && <span className="label">Speaking</span>}</div>
          </div>
          <div className={`tile ${speakingMe ? "tile--speaking" : ""} ${!aiIsCaller && verdict.level === "alert" ? "tile--alert" : ""}`}>
            <div className="tile__label">
              <span className="label tile__name">{aiIsCaller ? "You" : `You, as ${cust.name} · ${cust.account_mask}`}</span>
              <span className="label">{aiIsCaller ? "Agent" : "Caller"}</span>
            </div>
            <Viewport source="video" video={video} level={() => myLevel.current} chaos={!aiIsCaller ? alertChaos : 0} resolve={!aiIsCaller ? resolve : 0} label="Your camera, stylized" />
            <div className="tile__state">{holding && <span className="label">Mic open</span>}</div>
          </div>
          <div className="controls">
            <button
              type="button"
              className={`ptt ${holding ? "ptt--on" : ""}`}
              disabled={!live}
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture(e.pointerId);
                press();
              }}
              onPointerUp={release}
              onPointerCancel={release}
              onContextMenu={(e) => e.preventDefault()}
              aria-pressed={holding}
            >
              {holding ? "Listening, release to send" : "Hold to talk"}
              <kbd className="hide-sm">Space</kbd>
              <span className="ptt__level" style={{ width: `${Math.min(100, myLevelUi * 140)}%` }} />
            </button>
            <form className="typed" onSubmit={submit}>
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={micErr ? "Mic unavailable. Type what you'd say" : "Or type what you'd say"}
                aria-label="Type a message"
                disabled={!live}
                enterKeyHint="send"
              />
              <button type="submit" disabled={!live}>
                Send
              </button>
            </form>
            <div className="controls__row">
              <span className="label">{SCENARIO_LABEL[call.scenario] ?? (call.scenario || "Unknown scenario")}</span>
              {micErr && <span className="warning">{micErr}</span>}
            </div>
          </div>
        </div>

        <div className="room__right">
          <VerdictStrip v={verdict} />
          <Transcript
            lines={state.lines}
            notes={notes}
            active={active}
            onActive={setActive}
            scrollTo={scrollTo}
            who={who}
            empty={
              <p className="transcript__empty">
                {aiIsCaller
                  ? "The caller is about to speak. Treat it like any call: verify, then decide."
                  : "The bank agent will pick up. Convince them you're the customer."}
              </p>
            }
          />
        </div>
      </div>

      <div className="room__timeline">
        <span className="label">0:00</span>
        <Baseline spikes={spikes} cursor={Math.min(1, t / duration)} activeId={active} onSpike={focusNote} agitation={Math.max(0, (70 - state.trust) / 70) * 0.5} ariaLabel="Call timeline" />
        <span className="label num">{fmtTime(duration)}</span>
      </div>

      {state.phase === "ended" && (
        <div className="ended" role="dialog" aria-label="Call ended">
          <div className="ended__inner">
            <span className="label">Call ended{state.ended ? `, ${state.ended.reason.replace(/_/g, " ")}` : ""}</span>
            <h2 className="ended__title">
              {state.ended?.reveal
                ? state.ended.reveal.persona_label || "Call over."
                : state.error ?? "Call over."}
            </h2>
            {state.ended?.reveal && (
              <p className="label">
                {state.peak === "high" ? "Baseline raised an alert" : state.peak === "caution" ? "Baseline was watching" : "Baseline stayed clear"}
              </p>
            )}
            <div className="ended__actions">
              {state.ended?.report_id && (
                <button className="btn" type="button" onClick={() => navigate(`/report/${state.ended!.report_id}`)}>
                  See the report
                </button>
              )}
              <button className="btn btn--ghost" type="button" onClick={onAgain}>
                Take another call
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
