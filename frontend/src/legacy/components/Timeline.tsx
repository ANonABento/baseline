import { useMemo } from "react";
import { buildTimeline, fmtTime, LANES, SIGNAL_LABEL, type EvidenceItem, type TimelineMarker, type Tone } from "../../analysis";
import type { SignalEvent, TranscriptEvent } from "../../types";
import { SignalIcon } from "./icons";
import { cx, Panel } from "./Panel";
import { Tip } from "./Tip";
import { TONE } from "./tone";

const SEG_TONE: Record<Tone, string> = {
  none: "bg-slate-600/70 hover:bg-slate-500",
  ok: "bg-slate-600/70 hover:bg-slate-500",
  watch: "bg-amber-400/80 hover:bg-amber-300",
  flag: "bg-rose-500/85 hover:bg-rose-400",
};

/** Marker shape encodes tone (diamond = flag, dot = watch, ring = ok) so color isn't the only cue. */
function MarkerShape({ tone }: { tone: Tone }) {
  if (tone === "flag") return <span className="block h-3 w-3 rotate-45 rounded-[2px] bg-rose-500 ring-2 ring-slate-950" />;
  if (tone === "watch") return <span className="block h-2.5 w-2.5 rounded-full bg-amber-400 ring-2 ring-slate-950" />;
  return <span className="block h-2 w-2 rounded-full border-2 border-emerald-400/80 bg-slate-950" />;
}

function markerTip(m: TimelineMarker) {
  return (
    <>
      <div className="flex items-center gap-2 font-semibold">
        {SIGNAL_LABEL[m.lane]} · <span className={TONE[m.tone].text}>{TONE[m.tone].label}</span>
        <span className="ml-auto font-mono text-xs font-normal text-slate-400">{fmtTime(m.t)}</span>
      </div>
      <div className="mt-0.5 text-slate-300">{m.reason}</div>
      {m.patterns.length > 0 && <div className="mt-1 text-rose-200">Matched: {m.patterns.join(", ")}</div>}
      <div className="mt-1 font-mono text-xs text-slate-500">risk {m.score.toFixed(2)} · conf {m.confidence.toFixed(2)} · click to view line</div>
    </>
  );
}

function Track({ ticks, duration, playhead, className, children }: {
  ticks: number[]; duration: number; playhead: number | null; className?: string; children?: React.ReactNode;
}) {
  return (
    <div className={cx("relative", className)}>
      {ticks.map((t) => (
        <span key={t} className="absolute inset-y-0 w-px bg-slate-800/70" style={{ left: pct(t / duration) }} />
      ))}
      {playhead != null && <span className="absolute inset-y-0 z-10 w-px bg-indigo-400/70" style={{ left: pct(playhead) }} />}
      {children}
    </div>
  );
}

const pct = (x: number) => `${(x * 100).toFixed(3)}%`;

export function Timeline({ transcript, signals, evidence, elapsed, live, onSelect }: {
  transcript: TranscriptEvent[];
  signals: SignalEvent[];
  evidence: EvidenceItem[];
  /** seconds since the call started (drives the playhead) */
  elapsed: number | null;
  live: boolean;
  onSelect: (utteranceId: number) => void;
}) {
  const minDur = Math.max(30, Math.ceil(((live && elapsed) || 0) + 4));
  const tl = useMemo(() => buildTimeline(transcript, signals, evidence, minDur), [transcript, signals, evidence, minDur]);
  const step = tl.duration > 120 ? 30 : tl.duration > 60 ? 10 : 5;
  const ticks = Array.from({ length: Math.floor(tl.duration / step) + 1 }, (_, i) => i * step);
  const playhead = live && elapsed != null ? Math.min(1, elapsed / tl.duration) : null;

  const legend = (
    <div className="flex items-center gap-3 text-xs text-slate-400">
      <span className="flex items-center gap-1.5"><MarkerShape tone="flag" /> Flag</span>
      <span className="flex items-center gap-1.5"><MarkerShape tone="watch" /> Watch</span>
      <span className="flex items-center gap-1.5"><MarkerShape tone="ok" /> OK</span>
    </div>
  );

  return (
    <Panel title="Call timeline · where each signal fired" right={legend}>
      <div className="grid grid-cols-[8.5rem_1fr] gap-x-3 gap-y-1.5 text-xs">
        {/* axis */}
        <span />
        <div className="relative h-4 font-mono text-[0.7rem] tabular-nums text-slate-500">
          {ticks.map((t) => (
            <span key={t} className="absolute -translate-x-1/2 first:translate-x-0 last:-translate-x-full" style={{ left: pct(t / tl.duration) }}>{fmtTime(t)}</span>
          ))}
        </div>

        {/* utterances */}
        <span className="flex items-center gap-2 font-medium text-slate-300">
          <span className="h-3.5 w-3.5 rounded-sm border border-slate-500" aria-hidden /> Caller speech
        </span>
        <Track ticks={ticks} duration={tl.duration} playhead={playhead} className="h-6 rounded bg-slate-900">
          {tl.segments.map((s) => (
            <Tip
              key={s.utterance_id}
              as="span"
              className="absolute inset-y-1"
              style={{ left: pct(s.x0), width: `max(6px, ${pct(s.x1 - s.x0)})` }}
              content={<><div className="font-mono text-xs text-slate-400">{fmtTime(tl.duration * s.x0)}</div>{s.text}</>}
            >
              <button
                type="button"
                onClick={() => onSelect(s.utterance_id)}
                aria-label={`Line at ${fmtTime(tl.duration * s.x0)}: ${s.text}`}
                className={cx("block h-full w-full rounded-sm transition-colors", SEG_TONE[s.tone])}
              />
            </Tip>
          ))}
        </Track>

        {/* signal lanes */}
        {LANES.map((lane) => {
          const ms = tl.markers.filter((m) => m.lane === lane);
          return [
            <span key={`${lane}-l`} className="flex items-center gap-2 text-slate-400">
              <SignalIcon signal={lane} className="h-3.5 w-3.5" /> {SIGNAL_LABEL[lane]}
            </span>,
            <Track key={`${lane}-t`} ticks={ticks} duration={tl.duration} playhead={playhead} className="h-5 border-b border-slate-800/60">
              {ms.length === 0 && transcript.length > 0 && (
                <span className="absolute left-1 top-0.5 text-[0.7rem] italic text-slate-600">no reading yet</span>
              )}
              {ms.map((m) => (
                <Tip
                  key={m.key}
                  as="span"
                  className="absolute top-1/2 z-20 -translate-x-1/2 -translate-y-1/2"
                  style={{ left: pct(m.x) }}
                  content={markerTip(m)}
                >
                  <button
                    type="button"
                    onClick={() => onSelect(m.utterance_id)}
                    aria-label={`${SIGNAL_LABEL[m.lane]} ${TONE[m.tone].label} at ${fmtTime(m.t)}: ${m.reason}`}
                    className="grid h-5 w-5 place-items-center rounded transition-transform hover:scale-125"
                  >
                    <MarkerShape tone={m.tone} />
                  </button>
                </Tip>
              ))}
            </Track>,
          ];
        })}
      </div>
    </Panel>
  );
}
