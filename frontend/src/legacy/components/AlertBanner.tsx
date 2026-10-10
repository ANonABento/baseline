import { useEffect, useState } from "react";
import { SIGNAL_LABEL } from "../../analysis";
import type { AlertEvent, SignalName } from "../../types";
import { IconAlert, IconArrowRight, IconCheck, IconInfo, IconLink, IconX, SignalIcon } from "./icons";
import { cx } from "./Panel";

const RANK = { none: 0, caution: 1, high: 2 } as const;
const isSignal = (s: string): s is SignalName => s in SIGNAL_LABEL;

/** "spoof: synthetic artifacts..." -> { signal: "spoof", text: "synthetic artifacts..." } */
function splitReason(r: string): { signal: SignalName | null; text: string } {
  const m = /^(\w+):\s*(.*)$/s.exec(r);
  if (m && isSignal(m[1])) return { signal: m[1], text: m[2] };
  return { signal: null, text: r };
}

function SignalChips({ signals, tone }: { signals: string[]; tone: "high" | "caution" }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {signals.filter(isSignal).map((s) => (
        <span key={s} className={cx(
          "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold ring-1",
          tone === "high" ? "bg-rose-500/15 text-rose-100 ring-rose-400/40" : "bg-amber-400/15 text-amber-100 ring-amber-400/40",
        )}>
          <SignalIcon signal={s} className="h-3.5 w-3.5" /> {SIGNAL_LABEL[s]}
        </span>
      ))}
    </div>
  );
}

export function AlertBanner({ alert, phase }: { alert: AlertEvent | null; phase: "idle" | "live" | "ended" }) {
  // Dismissal is remembered per (level, #signals); any escalation brings the alert back.
  const [dismissed, setDismissed] = useState<{ rank: number; n: number } | null>(null);
  useEffect(() => {
    if (!alert || alert.level === "none") setDismissed(null);
  }, [alert]);

  if (!alert || alert.level === "none") {
    if (phase === "idle") return null;
    return (
      <div className="alert-in flex items-center gap-3 rounded-xl border border-emerald-500/25 bg-emerald-500/[0.06] px-4 py-2.5" role="status">
        <IconCheck className="h-5 w-5 shrink-0 text-emerald-400" />
        <span className="font-semibold text-emerald-200">No risk signals</span>
        <span className="text-sm text-slate-400">Proceed with standard verification.</span>
      </div>
    );
  }

  const high = alert.level === "high";
  const rank = RANK[alert.level];
  const isDismissed = dismissed != null && rank <= dismissed.rank && alert.signals.length <= dismissed.n;
  const label = high ? "High risk" : "Caution";
  const nSig = alert.signals.length;
  const agree = nSig > 1 ? `${nSig} independent signals agree` : nSig === 1 ? "1 signal fired" : "";

  if (isDismissed) {
    return (
      <button
        type="button"
        onClick={() => setDismissed(null)}
        className={cx(
          "flex w-full items-center gap-3 rounded-xl border px-4 py-2 text-left text-sm",
          high ? "border-rose-500/50 bg-rose-950/40 text-rose-100" : "border-amber-400/40 bg-amber-950/30 text-amber-100",
        )}
      >
        {high ? <IconAlert className="h-4 w-4" /> : <IconInfo className="h-4 w-4" />}
        <span className="font-semibold uppercase tracking-wide">{label}</span>
        <span className="truncate text-slate-300">{agree} · alert hidden</span>
        <span className="ml-auto shrink-0 font-medium underline-offset-2 hover:underline">Show</span>
      </button>
    );
  }

  const dismiss = (
    <button
      type="button"
      onClick={() => setDismissed({ rank, n: nSig })}
      className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-slate-300 hover:bg-white/10"
      aria-label="Dismiss alert (it reappears if risk escalates)"
    >
      <IconX className="h-3.5 w-3.5" /> Dismiss
    </button>
  );

  if (!high) {
    // Caution: a single amber bar, informative but calm.
    return (
      <div key="caution" className="alert-in rounded-xl border border-amber-400/50 bg-amber-950/35 px-4 py-3" role="alert">
        <div className="flex items-center gap-3">
          <IconInfo className="h-5 w-5 shrink-0 text-amber-300" />
          <span className="rounded bg-amber-400 px-2 py-0.5 text-xs font-bold uppercase tracking-wider text-slate-950">Caution</span>
          <SignalChips signals={alert.signals} tone="caution" />
          <div className="ml-auto">{dismiss}</div>
        </div>
        {alert.suggested_action && <p className="mt-2 text-[0.95rem] font-medium leading-snug text-amber-50">{alert.suggested_action}</p>}
      </div>
    );
  }

  return (
    <div key="high" className="alert-in alert-breathe max-h-[40vh] overflow-y-auto rounded-xl border border-rose-500/80 bg-gradient-to-b from-rose-950/90 to-rose-950/60" role="alert" aria-live="assertive">
      <div className="flex items-start gap-4 px-5 pb-4 pt-4">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-rose-500 text-white">
          <IconAlert className="h-6 w-6" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-xs font-bold uppercase tracking-[0.16em] text-rose-300">High risk · {agree}</div>
              <h2 className="mt-0.5 text-2xl font-semibold leading-tight text-white">Possible fraud on this call: stop and verify.</h2>
            </div>
            {dismiss}
          </div>
          <div className="mt-2"><SignalChips signals={alert.signals} tone="high" /></div>

          {alert.suggested_action && (
            <div className="mt-3 flex gap-3 rounded-lg bg-white px-4 py-3 text-slate-900">
              <IconArrowRight className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
              <div>
                <div className="text-[0.7rem] font-bold uppercase tracking-wider text-rose-700">Do this now</div>
                <p className="text-base font-semibold leading-snug">{alert.suggested_action}</p>
              </div>
            </div>
          )}

          {alert.reasons.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm text-rose-50/90">
              {alert.reasons.map((r) => {
                const { signal, text } = splitReason(r);
                return (
                  <li key={r} className="flex gap-2">
                    {signal ? <SignalIcon signal={signal} className="mt-0.5 h-4 w-4 shrink-0 text-rose-300" /> : <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-rose-300" />}
                    <span>{signal && <span className="font-semibold">{SIGNAL_LABEL[signal]}: </span>}{text}</span>
                  </li>
                );
              })}
            </ul>
          )}

          {alert.citations.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
              <span className="text-rose-300/80">Guidance:</span>
              {alert.citations.map((c) => (
                <a key={c.pattern_id} href={c.source} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-rose-100 underline-offset-2 hover:underline">
                  <IconLink className="h-3 w-3" /> {c.name}
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
