import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fmtTime, lineTriggers } from "./analysis";
import { AlertBanner, CallControls, CustomerPanel, FraudEvidence, SignalCards, Timeline, Transcript, TrustGauge } from "./components";
import { clipLabel } from "./components/CallControls";
import { LogoMark } from "./components/icons";
import { cx } from "./components/Panel";
import type { Focus } from "./components/Transcript";
import { micErrorMessage, startMic, type MicHandle } from "./mic";
import type { Clip, Customer } from "./types";
import { API_URL, useCall, type CallState } from "./useCall";

function useNow(active: boolean, ms = 500): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [active, ms]);
  return now;
}

function CallStatus({ state, elapsed }: { state: CallState; elapsed: number | null }) {
  const source = state.mode === "mic" || (!state.clip && state.phase !== "idle") ? "Live mic" : state.clip ? clipLabel(state.clip) : "";
  if (state.phase === "idle") {
    return <span className="text-sm text-slate-400">No active call</span>;
  }
  const live = state.phase === "live";
  return (
    <div className="flex items-center gap-2.5 text-sm">
      <span className={cx(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold uppercase tracking-wider",
        live ? "bg-rose-500/15 text-rose-200 ring-1 ring-rose-500/40" : "bg-slate-800 text-slate-300 ring-1 ring-slate-700",
      )}>
        <span className={cx("h-2 w-2 rounded-full", live ? "live-pulse bg-rose-500" : "bg-slate-500")} />
        {live ? "On call" : "Call ended"}
      </span>
      <span className="text-slate-200">{source}{state.mode === "replay" || (!live && state.clip) ? <span className="text-slate-500"> · replay</span> : null}</span>
      {elapsed != null && <span className="font-mono tabular-nums text-slate-400">{fmtTime(elapsed)}</span>}
    </div>
  );
}

function Connection({ conn, info }: { conn: CallState["conn"]; info: string }) {
  const meta = {
    open: { dot: "bg-emerald-400", label: "Connected" },
    connecting: { dot: "bg-amber-400 live-pulse", label: "Connecting…" },
    closed: { dot: "bg-rose-500", label: "Backend offline · retrying" },
  }[conn];
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400" title={info || undefined}>
      <span className={cx("h-2 w-2 rounded-full", meta.dot)} aria-hidden />
      <span className={conn === "closed" ? "text-rose-300" : undefined}>{meta.label}</span>
      {conn === "open" && info && <span className="hidden font-mono text-slate-500 xl:inline">· {info}</span>}
    </div>
  );
}

export default function App() {
  const { state, replay, startMicCall, stop, sendAudio } = useCall();
  const [clips, setClips] = useState<Clip[]>([]);
  const [selected, setSelected] = useState("");
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [micError, setMicError] = useState<string | null>(null);
  const [micLevel, setMicLevel] = useState(0);
  const [focus, setFocus] = useState<Focus | null>(null);
  const mic = useRef<MicHandle | null>(null);

  // (Re)load clips + customer whenever the socket (re)connects.
  useEffect(() => {
    if (state.conn !== "open") return;
    fetch(`${API_URL}/clips`).then((r) => r.json()).then((cs: Clip[]) => {
      setClips(cs);
      setSelected((cur) => cur || cs.find((c) => c.name.includes("takeover"))?.name || cs[0]?.name || "");
    }).catch(() => setClips([]));
    fetch(`${API_URL}/customer`).then((r) => r.json()).then(setCustomer).catch(() => undefined);
  }, [state.conn]);

  // Stop the mic if the call ends from the server side (or the socket drops).
  useEffect(() => {
    if (state.mode !== "mic" && mic.current) {
      mic.current.stop();
      mic.current = null;
    }
  }, [state.mode]);

  // New call -> clear transcript focus.
  useEffect(() => setFocus(null), [state.startedAt]);

  const stopAll = () => {
    mic.current?.stop();
    mic.current = null;
    stop();
  };

  const onMic = async () => {
    setMicError(null);
    try {
      startMicCall();
      mic.current = await startMic(sendAudio, setMicLevel);
    } catch (e) {
      setMicError(micErrorMessage(e));
      stop();
    }
  };

  useEffect(() => () => mic.current?.stop(), []);

  const jump = useCallback((utteranceId: number) => setFocus((f) => ({ utteranceId, n: (f?.n ?? 0) + 1 })), []);

  const now = useNow(state.phase === "live");
  const elapsed = state.startedAt ? Math.max(0, ((state.endedAt ?? now) - state.startedAt) / 1000) : null;
  const triggers = useMemo(() => lineTriggers(state.signalLog, state.evidence.items), [state.signalLog, state.evidence.items]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-6 border-b border-slate-800 bg-slate-950 px-5">
        <div className="flex items-center gap-2.5">
          <LogoMark />
          <span className="text-lg font-semibold tracking-tight text-white">Baseline</span>
          <span className="hidden border-l border-slate-700 pl-2.5 text-sm text-slate-400 md:inline">Agent co-pilot · call fraud defense</span>
        </div>
        <div className="flex flex-1 justify-center"><CallStatus state={state} elapsed={elapsed} /></div>
        <Connection conn={state.conn} info={state.backendInfo} />
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 lg:grid-cols-[minmax(16rem,20rem)_minmax(0,1fr)_minmax(21rem,27rem)] lg:overflow-hidden">
        {/* LEFT: who should be calling + call source + the fraud case file */}
        <aside className="flex min-h-0 flex-col gap-4" aria-label="Customer and call source">
          <CustomerPanel customer={customer} />
          <CallControls
            clips={clips}
            selected={selected}
            onSelect={setSelected}
            onReplay={() => selected && replay(selected)}
            onStop={stopAll}
            onMic={onMic}
            mode={state.mode}
            connected={state.conn === "open"}
            micError={micError}
            micLevel={micLevel}
          />
          {state.error && <p className="rounded-lg border border-rose-500/30 bg-rose-950/40 p-3 text-xs text-rose-200" role="alert">{state.error}</p>}
          <FraudEvidence evidence={state.evidence} transcript={state.transcript} onJump={jump} className="min-h-[12rem] flex-1" />
        </aside>

        {/* CENTER: alert on top, the conversation, and the timeline of what fired when */}
        <section className="flex min-h-0 flex-col gap-3" aria-label="Call">
          <AlertBanner alert={state.alert} phase={state.phase} />
          <Transcript items={state.transcript} live={state.phase === "live"} triggers={triggers} focus={focus} />
          <Timeline
            transcript={state.transcript}
            signals={state.signalLog}
            evidence={state.evidence.items}
            elapsed={elapsed}
            live={state.phase === "live"}
            onSelect={jump}
          />
        </section>

        {/* RIGHT: fused score + independent signals (components owned by V) */}
        <aside className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-0.5" aria-label="Risk signals">
          <TrustGauge score={state.trust} history={state.trustHistory} />
          <div className="rail-signals">
            <SignalCards signals={state.signals} />
          </div>
        </aside>
      </main>

      {/* SLOT: ProofStrip (owned by V). Replace this footer's placeholder with <ProofStrip />. */}
      <footer data-slot="proof-strip" className="flex h-10 shrink-0 items-center gap-4 border-t border-slate-800 bg-slate-950 px-5 text-xs text-slate-500">
        <span className="rounded border border-dashed border-slate-700 px-2 py-0.5 font-mono text-slate-600">ProofStrip slot</span>
        <span>Accuracy over the night · per-utterance latency</span>
        <span className="ml-auto">Runs on one laptop · call audio never leaves the bank</span>
      </footer>
    </div>
  );
}
