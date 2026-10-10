import type { SignalEvent, SignalName } from "../../types";
import { cx } from "./Panel";

const SIGNAL_META: Record<SignalName, { label: string; sub: string }> = {
  speaker: { label: "Voice match", sub: "vs enrolled voiceprint" },
  spoof: { label: "Synthetic voice", sub: "clone / voice-changer artifacts" },
  fraud: { label: "Fraud pattern", sub: "script vs playbook" },
  prosody: { label: "Pressure", sub: "vs caller's own baseline" },
};
const ORDER: SignalName[] = ["speaker", "spoof", "fraud", "prosody"];

export function SignalCards({ signals }: { signals: Partial<Record<SignalName, SignalEvent>> }) {
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      {ORDER.map((k) => {
        const s = signals[k];
        const inactive = !s || s.confidence === 0;
        const risk = s?.score ?? 0;
        const tone = inactive ? "slate" : risk >= 0.5 ? "rose" : risk >= 0.25 ? "amber" : "emerald";
        const ring = { slate: "border-slate-800", rose: "border-rose-500/60", amber: "border-amber-500/50", emerald: "border-emerald-500/40" }[tone];
        const bar = { slate: "bg-slate-700", rose: "bg-rose-500", amber: "bg-amber-400", emerald: "bg-emerald-400" }[tone];
        const verdict = inactive ? "—" : risk >= 0.5 ? "FLAG" : risk >= 0.25 ? "WATCH" : "OK";
        const citations = (s?.details?.citations as { pattern_id: string; name: string; source: string }[] | undefined) ?? [];
        return (
          <div key={k} className={cx("rounded-xl border bg-slate-900/60 p-4", ring)}>
            <div className="flex items-start justify-between">
              <div>
                <div className="font-semibold text-slate-100">{SIGNAL_META[k].label}</div>
                <div className="text-[11px] text-slate-500">{SIGNAL_META[k].sub}</div>
              </div>
              <span className={cx("rounded px-1.5 py-0.5 font-mono text-[10px] font-bold",
                tone === "rose" ? "bg-rose-500/20 text-rose-300" : tone === "amber" ? "bg-amber-500/20 text-amber-300"
                  : tone === "emerald" ? "bg-emerald-500/20 text-emerald-300" : "bg-slate-800 text-slate-500")}>{verdict}</span>
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded bg-slate-800">
              <div className={cx("h-full transition-all duration-500", bar)} style={{ width: `${inactive ? 0 : risk * 100}%` }} />
            </div>
            <div className="mt-1 flex justify-between font-mono text-[10px] text-slate-500">
              <span>risk {inactive ? "—" : risk.toFixed(2)}</span>
              <span>conf {s ? s.confidence.toFixed(2) : "—"}</span>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-300">{s?.reason ?? "Waiting for speech…"}</p>
            {citations.length > 0 && (
              <ul className="mt-2 space-y-0.5">
                {citations.slice(0, 3).map((c) => (
                  <li key={c.pattern_id} className="truncate text-[11px]">
                    <a href={c.source} target="_blank" rel="noreferrer" className="text-indigo-300 hover:underline">↗ {c.name}</a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}
