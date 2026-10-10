import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { fmtTime, worstTone, type LineTrigger } from "../../analysis";
import type { TranscriptEvent } from "../../types";
import { SignalIcon } from "./icons";
import { cx, Panel } from "./Panel";
import { Tip } from "./Tip";
import { TONE } from "./tone";

export interface Focus {
  utteranceId: number;
  /** bumps on every request so re-clicking the same line flashes again */
  n: number;
}

const MARKER: Record<string, string> = {
  none: "border-l-transparent",
  ok: "border-l-transparent",
  watch: "border-l-amber-400",
  flag: "border-l-rose-500",
};

export function Transcript({ items, live, triggers, focus }: {
  items: TranscriptEvent[];
  live: boolean;
  triggers: Map<number, LineTrigger[]>;
  focus: Focus | null;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true); // follow new lines while the user is at the bottom
  const [flash, setFlash] = useState<Focus | null>(null);

  const onScroll = () => {
    const el = scroller.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };

  useLayoutEffect(() => {
    const el = scroller.current;
    if (items.length === 0) stick.current = true;
    if (el && stick.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [items.length]);

  useEffect(() => {
    if (!focus) return;
    const el = scroller.current;
    const line = el?.querySelector<HTMLElement>(`[data-utt="${focus.utteranceId}"]`);
    if (!el || !line) return;
    const top = line.offsetTop - el.clientHeight / 2 + line.offsetHeight / 2;
    el.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    stick.current = false;
    setFlash(focus);
  }, [focus]);

  const flagged = [...triggers.values()].filter((t) => t.length).length;

  return (
    <Panel
      title="Live transcript · caller"
      className="flex min-h-0 flex-col"
      right={
        <div className="flex items-center gap-3 text-xs">
          {flagged > 0 && <span className="text-slate-400">{flagged} flagged line{flagged === 1 ? "" : "s"}</span>}
          {live && (
            <span className="flex items-center gap-1.5 font-medium text-rose-300">
              <span className="live-pulse h-2 w-2 rounded-full bg-rose-500" /> LIVE
            </span>
          )}
        </div>
      }
    >
      <div ref={scroller} onScroll={onScroll} className="relative min-h-0 flex-1 overflow-y-auto pr-1" aria-live="polite">
        {items.length === 0 && (
          <div className="grid h-full place-items-center text-center">
            <div className="max-w-sm text-slate-500">
              <p className="text-base text-slate-400">No call in progress</p>
              <p className="mt-1 text-sm">Pick a recorded call on the left and press <span className="text-slate-300">Start replay</span>, or use the live mic.</p>
            </div>
          </div>
        )}
        <ol className="space-y-1">
          {items.map((t) => {
            const trg = triggers.get(t.utterance_id) ?? [];
            const tone = worstTone(trg.map((x) => x.tone));
            const flashing = flash?.utteranceId === t.utterance_id;
            return (
              <li
                key={flashing ? `${t.utterance_id}-${flash.n}` : t.utterance_id}
                data-utt={t.utterance_id}
                className={cx(
                  "flex gap-4 rounded-r-lg border-l-[3px] py-2 pl-3 pr-2",
                  MARKER[tone],
                  tone === "flag" && "bg-rose-500/[0.06]",
                  tone === "watch" && "bg-amber-500/[0.05]",
                  flashing ? "line-flash" : "line-in",
                )}
              >
                <span className="w-11 shrink-0 pt-0.5 text-right font-mono text-xs tabular-nums text-slate-500">{fmtTime(t.t_start)}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-[1.0625rem] leading-7 text-slate-100">{t.text}</p>
                  {trg.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {trg.map((x) => (
                        <Tip
                          key={`${x.signal}-${x.patternId ?? ""}`}
                          tabIndex={0}
                          className={cx("inline-flex cursor-help items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1", TONE[x.tone].chip)}
                          content={<><div className="font-semibold">{x.label}</div><div className="mt-0.5 text-slate-300">{x.reason}</div></>}
                        >
                          <SignalIcon signal={x.signal} className="h-3.5 w-3.5" />
                          {x.label}
                        </Tip>
                      ))}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </Panel>
  );
}
