import type { Tone } from "../analysis";
import type { Severity } from "../types";

// One palette for risk across the dashboard. Text labels/icons always accompany color.
export const TONE: Record<Tone, { text: string; bg: string; border: string; dot: string; chip: string; label: string }> = {
  none: { text: "text-slate-400", bg: "bg-slate-800", border: "border-slate-700", dot: "bg-slate-600", chip: "bg-slate-800 text-slate-300 ring-slate-700", label: "No data" },
  ok: { text: "text-emerald-300", bg: "bg-emerald-500/10", border: "border-emerald-500/40", dot: "bg-emerald-400", chip: "bg-emerald-500/10 text-emerald-200 ring-emerald-500/30", label: "OK" },
  watch: { text: "text-amber-300", bg: "bg-amber-500/10", border: "border-amber-400/60", dot: "bg-amber-400", chip: "bg-amber-500/15 text-amber-100 ring-amber-400/40", label: "Watch" },
  flag: { text: "text-rose-300", bg: "bg-rose-500/10", border: "border-rose-500/70", dot: "bg-rose-500", chip: "bg-rose-500/15 text-rose-100 ring-rose-500/40", label: "Flag" },
};

export const SEVERITY_STYLE: Record<Severity, { chip: string; bar: string; label: string }> = {
  high: { chip: "bg-rose-500/15 text-rose-200 ring-1 ring-rose-500/40", bar: "bg-rose-500", label: "High" },
  medium: { chip: "bg-amber-500/15 text-amber-100 ring-1 ring-amber-400/40", bar: "bg-amber-400", label: "Medium" },
  low: { chip: "bg-slate-700/60 text-slate-200 ring-1 ring-slate-600", bar: "bg-slate-400", label: "Low" },
};
