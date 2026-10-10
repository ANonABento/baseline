import { cx, Panel } from "./Panel";

export function TrustGauge({ score, history }: { score: number; history: number[] }) {
  const color = score >= 75 ? "text-emerald-400" : score >= 45 ? "text-amber-400" : "text-rose-400";
  const stroke = score >= 75 ? "#34d399" : score >= 45 ? "#fbbf24" : "#fb7185";
  const w = 220, h = 44;
  const pts = history.map((v, i) => `${(i / Math.max(1, history.length - 1)) * w},${h - (v / 100) * h}`).join(" ");
  return (
    <Panel title="Trust score">
      <div className="flex items-end gap-2">
        <span className={cx("font-mono text-6xl font-semibold tabular-nums leading-none", color)}>{Math.round(score)}</span>
        <span className="mb-1 text-sm text-slate-500">/ 100</span>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="mt-4 h-11 w-full" preserveAspectRatio="none">
        <polyline points={pts} fill="none" stroke={stroke} strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <p className="mt-2 text-xs text-slate-500">100 − weighted risk from independent signals, smoothed.</p>
    </Panel>
  );
}
