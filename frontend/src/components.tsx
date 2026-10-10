import { useEffect, useRef } from "react";
import type { AlertEvent, Clip, Customer, SignalEvent, SignalName, TranscriptEvent } from "./types";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export function Panel({ title, right, children, className }: {
  title: string; right?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <section className={cx("rounded-xl border border-slate-800 bg-slate-900/60 p-4", className)}>
      <header className="mb-3 flex items-center justify-between">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">{title}</h2>
        {right}
      </header>
      {children}
    </section>
  );
}

export function CustomerPanel({ customer }: { customer: Customer | null }) {
  const c = customer ?? {
    id: "CUST-004217", name: "Margaret Chen", enrolled: true, voiceprint: "stub (not enrolled yet)",
    phone_on_file: "(650) 555-0142", member_since: "2009", segment: "Retail / senior",
  };
  const rows: [string, string][] = [
    ["Customer ID", c.id],
    ["Phone on file", c.phone_on_file],
    ["Member since", c.member_since],
    ["Segment", c.segment],
    ["Voiceprint", c.voiceprint],
  ];
  return (
    <Panel title="Customer on file">
      <div className="mb-4 flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-full bg-indigo-500/20 text-lg font-semibold text-indigo-300">
          {c.name.split(" ").map((p) => p[0]).join("")}
        </div>
        <div>
          <div className="font-semibold text-slate-100">{c.name}</div>
          <div className="text-xs text-emerald-400">{c.enrolled ? "● Voice baseline enrolled" : "○ Not enrolled"}</div>
        </div>
      </div>
      <dl className="space-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2">
            <dt className="text-slate-500">{k}</dt>
            <dd className="text-right font-mono text-xs leading-5 text-slate-300">{v}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

export function CallControls({ clips, selected, onSelect, onReplay, onStop, onMic, mode, connected, micError }: {
  clips: Clip[]; selected: string; onSelect: (c: string) => void; onReplay: () => void; onStop: () => void;
  onMic: () => void; mode: string; connected: boolean; micError: string | null;
}) {
  const busy = mode !== "idle";
  return (
    <Panel title="Call source">
      <label className="mb-1 block text-xs text-slate-500">Replay a recorded call</label>
      <select
        className="mb-3 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-indigo-500"
        value={selected}
        onChange={(e) => onSelect(e.target.value)}
        disabled={busy}
      >
        {clips.length === 0 && <option value="">No clips in data/demo/</option>}
        {clips.map((c) => (
          <option key={c.name} value={c.name}>
            {c.name} {c.duration_s ? `· ${c.duration_s}s` : ""} {c.has_transcript ? "" : "· no transcript"}
          </option>
        ))}
      </select>
      <div className="flex gap-2">
        {busy ? (
          <button onClick={onStop} className="flex-1 rounded-lg bg-slate-700 px-3 py-2 text-sm font-semibold hover:bg-slate-600">
            ■ Stop
          </button>
        ) : (
          <>
            <button
              onClick={onReplay}
              disabled={!connected || !selected}
              className="flex-1 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-40"
            >
              ▶ Start replay
            </button>
            <button
              onClick={onMic}
              disabled={!connected}
              className="rounded-lg border border-slate-700 px-3 py-2 text-sm font-semibold hover:bg-slate-800 disabled:opacity-40"
              title="Stream your microphone (16 kHz PCM)"
            >
              🎙 Live mic
            </button>
          </>
        )}
      </div>
      {mode === "mic" && <p className="mt-2 text-xs text-rose-300">● Live mic streaming…</p>}
      {micError && <p className="mt-2 text-xs text-rose-400">{micError}</p>}
    </Panel>
  );
}

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

export function Transcript({ items, live }: { items: TranscriptEvent[]; live: boolean }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), [items.length]);
  return (
    <Panel title="Live transcript · caller" className="flex min-h-0 flex-col"
      right={live ? <span className="text-xs text-rose-400">● live</span> : null}>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {items.length === 0 && <p className="text-sm text-slate-600">Start a replay or the live mic to see the transcript.</p>}
        {items.map((t) => (
          <div key={t.utterance_id} className="flex gap-3">
            <span className="w-12 shrink-0 pt-0.5 text-right font-mono text-[11px] text-slate-500">
              {Math.floor(t.t_start / 60)}:{String(Math.floor(t.t_start % 60)).padStart(2, "0")}
            </span>
            <p className="text-sm leading-6 text-slate-200">{t.text}</p>
          </div>
        ))}
        <div ref={end} />
      </div>
    </Panel>
  );
}
