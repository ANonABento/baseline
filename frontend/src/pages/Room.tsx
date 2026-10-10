import { AgendaPanel } from "../components/Agenda";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fmtTime } from "../analysis";
import { Baseline } from "../components/Baseline";
import { Mark } from "../components/Chrome";
import { Signals } from "../components/Signals";
import { Transcript } from "../components/Transcript";
import { TwinPanel } from "../components/Twin";
import { twinView } from "../lib/twin";
import { Viewport } from "../components/Viewport";
import { currentCamera, micChoice } from "../lib/media";
import { buildNotes, spikesFromNotes, TIER_GLYPH, verdictOf, type Note } from "../lib/notes";
import { linkTo, navigate } from "../lib/prefs";
import { elapsed, type SessionState } from "../lib/session";
import { micErrorMessage, startMic, type MicHandle } from "../mic";
import { SCENARIO_LABEL } from "./Lobby";

interface Props {
  state: SessionState;
  aiLevel: () => number;
  onHangup: () => void;
  onSuspect: () => void;
  onText: (t: string) => void;
  onPcm: (pcm: ArrayBuffer) => void;
  onBargeIn: () => void;
  onPtt: (state: "down" | "up") => void;
  onAgain: () => void;
}

const TAIL_MS = 400; // keep sending after release (worklet latency), then tell the server the turn is over
const PREROLL_BYTES = 16000 * 2 * 0.3; // last 300 ms of 16 kHz PCM16, sent on press so the first syllable survives

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

/** Who the AI caller claims to be, per scenario (role client). */
export function callerClaim(scenario: string, name: string): string {
  switch (scenario) {
    case "grandchild":
      return `Says he's ${name}`;
    case "fake_bank":
      return "Says: First City fraud dept.";
    case "irs":
      return "Says: IRS officer";
    case "tech_support":
      return "Says: Windows support";
    case "fraud_dept_slow":
      return "Says: First City fraud team";
    case "bank_investigation":
      return "Says: First City security";
    case "amazon_refund":
      return "Says: Amazon order team";
    default:
      return "Unknown caller";
  }
}

export const ACTION_LABEL: Record<string, string> = {
  family_alert: "Trusted contact alerted",
  bank_hold: "Outgoing transfers held",
};

/** The moment Baseline steps in on the client's phone: restrained, but unmistakable. */
export function InterventionBanner({ state, onHangup }: { state: SessionState; onHangup: () => void }) {
  const iv = state.interventions.at(-1);
  if (!iv) return null;
  const live = state.phase === "live";
  return (
    <section className={`iv iv--${iv.level}`} role="alert" aria-live="assertive" key={iv.reason_id + iv.level}>
      <div className="iv__head">
        <span className="label iv__who">{iv.to === "victim" ? "Baseline warned the person you called" : "Baseline, First City fraud protection"}</span>
        {state.baselineSpeaking && (
          <span className="label iv__speaking" aria-label="Baseline is speaking">
            <i />
            <i />
            <i />
            <i />
            Speaking to you
          </span>
        )}
      </div>
      <p className="iv__msg">{iv.message}</p>
      <button className={`btn iv__hang ${iv.level === "high" ? "btn--red" : "btn--danger"}`} type="button" onClick={onHangup} disabled={!live}>
        Hang up
      </button>
      {state.actions.length > 0 && (
        <ul className="iv__actions" aria-label="What First City did">
          {state.actions.map((a) => (
            <li key={a.kind} title={a.message}>
              {a.message}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** "You flagged it at 0:41 / Baseline flagged it at 0:12". */
export function YouVsBaseline({ state, compact = false }: { state: SessionState; compact?: boolean }) {
  const you = state.suspectT;
  const bl = state.flagT;
  const warned = state.interventions.some((i) => i.level === "high")
    ? "Warned you out loud"
    : state.interventions.length
      ? "Warned you on screen"
      : null;
  const did = [warned, ...state.actions.map((a) => ACTION_LABEL[a.kind] ?? a.message)].filter(Boolean) as string[];
  return (
    <div className={`yvb ${compact ? "yvb--compact" : ""}`}>
      <div className="yvb__col">
        <span className="label">You</span>
        <span className={`yvb__t ${you == null ? "yvb__t--none" : ""}`}>{you == null ? "Never flagged it" : `Flagged it at ${fmtTime(you)}`}</span>
      </div>
      <div className="yvb__col">
        <span className="label">Baseline</span>
        <span className={`yvb__t ${bl == null ? "yvb__t--none" : "yvb__t--bl"}`}>{bl == null ? "Never flagged it" : `Flagged it at ${fmtTime(bl)}`}</span>
      </div>
      {did.length > 0 && (
        <div className="yvb__did">
          <span className="label">What Baseline did</span>
          <ul>
            {did.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function Room({ state, aiLevel, onHangup, onSuspect, onText, onPcm, onBargeIn, onPtt, onAgain }: Props) {
  const live = state.phase === "live";
  const now = useNow(live);
  const t = elapsed(state, now);
  const call = state.call!;
  const role = state.ended?.reveal.role ?? call.role;
  const notes = useMemo(() => buildNotes(state.lines, state.signals, state.evidence.items), [state.lines, state.signals, state.evidence.items]);
  const twin = useMemo(() => twinView(state, role === "scammer" ? "visitor" : "ai"), [state.lines, state.signals, state.pressure, state.decisions]);
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
  const preroll = useRef<ArrayBuffer[]>([]);
  const upTimer = useRef<number | undefined>(undefined);

  // ---- mic: open once the call is live; only stream while holding (+ a short tail so the VAD closes)
  const ensureMic = useCallback(async () => {
    if (mic.current) return true;
    try {
      mic.current = await startMic(
        (pcm) => {
          if (holdingRef.current || performance.now() < sendUntil.current) {
            onPcm(pcm);
            return;
          }
          const buf = preroll.current;
          buf.push(pcm);
          let bytes = buf.reduce((n, b) => n + b.byteLength, 0);
          while (buf.length > 1 && bytes - buf[0].byteLength >= PREROLL_BYTES) bytes -= buf.shift()!.byteLength;
        },
        (lv) => {
          myLevel.current = lv;
          if (holdingRef.current) setMyLevelUi(lv);
        },
        micChoice.deviceId || undefined,
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
    window.clearTimeout(upTimer.current);
    onPtt("down");
    for (const b of preroll.current) onPcm(b);
    preroll.current = [];
    void ensureMic();
  }, [live, ensureMic, onBargeIn, onPtt, onPcm]);
  const release = useCallback(() => {
    if (!holdingRef.current) return;
    holdingRef.current = false;
    sendUntil.current = performance.now() + TAIL_MS;
    window.clearTimeout(upTimer.current);
    upTimer.current = window.setTimeout(() => {
      if (!holdingRef.current) onPtt("up");
    }, TAIL_MS + 60);
    setHolding(false);
    setMyLevelUi(0);
  }, [onPtt]);
  useEffect(() => () => window.clearTimeout(upTimer.current), []);

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
  const who = aiIsCaller ? ({ ai: "Caller", visitor: "You" } as const) : ({ ai: call.agenda?.target.name ?? "Them", visitor: "You" } as const);

  return (
    <div className="room">
      <header className="room__bar">
        <a href="/" onClick={linkTo("/")} className="wordmark" aria-label="Baseline home">
          <Mark alert={verdict.level === "alert"} />
          <span className="hide-sm">Baseline</span>
        </a>
        <span className="role-badge">{role === "scammer" ? "You: scammer" : `You: ${call.visitor_as ?? cust.name}`}</span>
        {live && <span className="live-dot" aria-hidden />}
        <span className="room__timer" aria-label="Call time">
          {fmtTime(t)}
        </span>
        {state.warning && live && <span className="warning hide-sm">{Math.ceil(left)} s left</span>}
        <span style={{ flex: 1 }} />
        <button className="btn btn--danger btn--small" type="button" onClick={onHangup} disabled={!live}>
          Hang up
        </button>
      </header>

      <div className="iv-slot">
        <InterventionBanner state={state} onHangup={onHangup} />
      </div>

      <div className="room__main">
        <div className="room__left">
          <div className={`tile ${speakingAi ? "tile--speaking" : ""} ${aiIsCaller && verdict.level === "alert" ? "tile--alert" : ""}`}>
            <div className="tile__label">
              <span className="label tile__name">{aiIsCaller ? callerClaim(call.scenario, cust.name) : (call.agenda?.target.name ?? "The person you called")}</span>
              <span className="label">{aiIsCaller ? "Caller (AI)" : "Protected by Baseline (AI)"}</span>
            </div>
            <Viewport source="head" level={aiLevel} chaos={aiIsCaller ? alertChaos : 0} resolve={aiIsCaller ? resolve : 0.4} drift label="The AI caller" />
            <div className="tile__state">{speakingAi && <span className="label">Speaking</span>}</div>
          </div>
          <div className={`tile ${speakingMe ? "tile--speaking" : ""} ${!aiIsCaller && verdict.level === "alert" ? "tile--alert" : ""}`}>
            <div className="tile__label">
              <span className="label tile__name">{aiIsCaller ? `You, ${call.visitor_as ?? cust.name}` : "You, the scammer"}</span>
              <span className="label">{aiIsCaller ? "Protected by Baseline" : "Caller"}</span>
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
              {aiIsCaller ? (
                state.suspectT == null ? (
                  <button type="button" className="suspect" onClick={onSuspect} disabled={!live}>
                    This feels like a scam
                  </button>
                ) : (
                  <span className="suspect suspect--done">You flagged it at {fmtTime(state.suspectT)}</span>
                )
              ) : (
                <span className="label">{call.scenario_label ?? SCENARIO_LABEL[call.scenario] ?? (call.scenario || "Unknown scenario")}</span>
              )}
              {micErr && <span className="warning">{micErr}</span>}
            </div>
          </div>
        </div>

        <div className="room__right">
          {/* role client: the banner speaks to the client; agent-side "say this" scripts would confuse */}
          {!aiIsCaller && call.agenda && <AgendaPanel agenda={call.agenda} />}
          <VerdictStrip v={{ ...verdict, sayThis: null }} />
          <details className="twin__more" open>
            <summary className="label">Digital Twin and behavioural signals</summary>
            <TwinPanel twin={twin} duration={duration} />
            <Signals behaviour={state.behaviour} signals={state.signals} />
          </details>
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
                  ? "Your phone is ringing. Answer it like any call. Baseline is listening on both sides."
                  : `${call.agenda?.target.name ?? "They"} will pick up. Your agenda is on the side; hold Space to talk.`}
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
            <span className="label">{state.ended?.reveal?.persona_label ? "Call ended. The caller was" : "Call ended"}</span>
            <h2 className="ended__title">
              {state.ended?.reveal
                ? state.ended.reveal.persona_label || "Call over."
                : state.error ?? "Call over."}
            </h2>
            {state.ended?.reveal?.summary && <p className="ended__summary">{state.ended.reveal.summary}</p>}
            {state.ended?.reveal && aiIsCaller && <YouVsBaseline state={state} />}
            {state.ended?.reveal && !aiIsCaller && (
              <p className="label">
                {state.peak === "high" ? "Baseline raised an alert" : state.peak === "caution" ? "Baseline was watching" : "You got past Baseline"}
              </p>
            )}
            <div className="ended__actions">
              {state.ended?.report_id && (
                <button className="btn" type="button" onClick={() => navigate(`/report/${state.ended!.report_id}`)}>
                  See the report and your Digital Twin credential
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
