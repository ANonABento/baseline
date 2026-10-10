import { useEffect, useRef } from "react";
import type { TranscriptEvent } from "../types";
import { Panel } from "./Panel";

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
