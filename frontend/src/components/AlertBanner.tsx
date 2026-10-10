import type { AlertEvent } from "../types";
import { cx } from "./Panel";

export function AlertBanner({ alert }: { alert: AlertEvent | null }) {
  if (!alert || alert.level === "none") {
    return (
      <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-5 py-4">
        <div className="font-semibold text-emerald-300">No risk signals</div>
        <div className="text-sm text-slate-400">Proceed with standard verification.</div>
      </div>
    );
  }
  const high = alert.level === "high";
  return (
    <div className={cx("rounded-xl border px-5 py-4", high ? "border-rose-500 bg-rose-950/60 shadow-[0_0_40px_-10px] shadow-rose-500/50" : "border-amber-500/70 bg-amber-950/40")}>
      <div className="flex items-center gap-3">
        <span className={cx("rounded px-2 py-0.5 font-mono text-xs font-bold", high ? "bg-rose-500 text-white" : "bg-amber-400 text-slate-950")}>
          {high ? "HIGH RISK" : "CAUTION"}
        </span>
        <span className="text-sm text-slate-300">
          {alert.signals.length} independent signal{alert.signals.length === 1 ? "" : "s"}: {alert.signals.join(" + ")}
        </span>
      </div>
      {alert.suggested_action && (
        <p className={cx("mt-3 text-base font-semibold leading-6", high ? "text-rose-100" : "text-amber-100")}>
          {alert.suggested_action}
        </p>
      )}
      {alert.reasons.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-slate-300">
          {alert.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
    </div>
  );
}
