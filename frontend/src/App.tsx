import { useEffect, useRef, useState } from "react";
import { AlertBanner, CallControls, CustomerPanel, SignalCards, Transcript, TrustGauge } from "./components";
import { startMic, type MicHandle } from "./mic";
import type { Clip, Customer } from "./types";
import { API_URL, useCall } from "./useCall";

export default function App() {
  const { state, replay, startMicCall, stop, sendAudio } = useCall();
  const [clips, setClips] = useState<Clip[]>([]);
  const [selected, setSelected] = useState("");
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [micError, setMicError] = useState<string | null>(null);
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

  const stopAll = () => {
    mic.current?.stop();
    mic.current = null;
    stop();
  };

  const onMic = async () => {
    setMicError(null);
    try {
      startMicCall();
      mic.current = await startMic(sendAudio);
    } catch (e) {
      setMicError(`Mic unavailable: ${(e as Error).message}`);
      stop();
    }
  };

  useEffect(() => () => mic.current?.stop(), []);

  const connBadge = {
    open: "bg-emerald-500/15 text-emerald-300",
    connecting: "bg-amber-500/15 text-amber-300",
    closed: "bg-rose-500/15 text-rose-300",
  }[state.conn];

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-slate-800 px-6 py-3">
        <div className="flex items-baseline gap-3">
          <span className="text-lg font-bold tracking-tight text-slate-50">Baseline</span>
          <span className="text-xs text-slate-500">Agent co-pilot · voice fraud defense</span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          {state.clip && state.mode === "replay" && <span className="text-slate-400">Replaying {state.clip}</span>}
          <span className={`rounded-full px-2.5 py-1 font-medium ${connBadge}`}>backend {state.conn}</span>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-12 gap-4 p-4">
        <aside className="col-span-12 space-y-4 lg:col-span-3">
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
          />
          {state.error && <p className="rounded-lg bg-rose-950/50 p-3 text-xs text-rose-300">{state.error}</p>}
        </aside>

        <section className="col-span-12 flex min-h-0 flex-col gap-4 lg:col-span-9">
          <AlertBanner alert={state.alert} />
          <div className="grid gap-4 md:grid-cols-[240px_1fr]">
            <TrustGauge score={state.trust} history={state.trustHistory} />
            <SignalCards signals={state.signals} />
          </div>
          <Transcript items={state.transcript} live={state.mode !== "idle"} />
        </section>
      </main>
    </div>
  );
}
