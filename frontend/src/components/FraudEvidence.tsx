import { fmtTime, type EvidenceState } from "../analysis";
import type { Severity, TranscriptEvent } from "../types";
import { IconAlert, IconArrowRight, IconInfo, IconLink, IconQuote } from "./icons";
import { cx, Panel } from "./Panel";
import { SEVERITY_STYLE } from "./tone";

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function engineLabel(engine: string | null, model: string | null): string | null {
  if (!engine) return null;
  const e = engine.toLowerCase();
  if (e === "llm") return model ? `LLM · ${model.split("/").pop()}` : "LLM";
  if (e.startsWith("keyword")) return "Keyword rules";
  return engine;
}

function SeverityChip({ severity }: { severity: Severity }) {
  const s = SEVERITY_STYLE[severity];
  return (
    <span className={cx("inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wide", s.chip)}>
      {severity === "low" ? <IconInfo className="h-3 w-3" /> : <IconAlert className="h-3 w-3" />}
      {s.label}
    </span>
  );
}

export function FraudEvidence({ evidence, transcript, onJump, className }: {
  evidence: EvidenceState;
  transcript: TranscriptEvent[];
  onJump: (utteranceId: number) => void;
  className?: string;
}) {
  const engine = engineLabel(evidence.engine, evidence.model);
  const byId = new Map(transcript.map((t) => [t.utterance_id, t]));
  return (
    <Panel
      title={`Fraud evidence${evidence.items.length ? ` · ${evidence.items.length}` : ""}`}
      className={cx("flex min-h-0 flex-col", className)}
      right={engine && <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[0.7rem] text-slate-400" title="Analyzer that produced this evidence">{engine}</span>}
    >
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {evidence.items.length === 0 && (
          <p className="text-sm text-slate-500">No fraud or social-engineering patterns matched. Each match will appear here with the quoted line and its source.</p>
        )}
        {evidence.items.map((p) => {
          const line = byId.get(p.utterance_id);
          return (
            <article key={p.id} className="relative overflow-hidden rounded-lg border border-slate-800 bg-slate-950/60 p-3 pl-4">
              <span className={cx("absolute inset-y-0 left-0 w-1", SEVERITY_STYLE[p.severity].bar)} aria-hidden />
              <header className="flex items-start justify-between gap-2">
                <h3 className="text-[0.95rem] font-semibold leading-snug text-slate-100">{p.name}</h3>
                <SeverityChip severity={p.severity} />
              </header>
              {p.quote && (
                <button
                  type="button"
                  onClick={() => onJump(p.utterance_id)}
                  className="group mt-2 flex w-full gap-2 rounded-md bg-slate-900 px-2.5 py-2 text-left hover:bg-slate-800"
                  title="Show this line in the transcript"
                >
                  <IconQuote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm italic leading-snug text-slate-200">{p.quote}</span>
                    <span className="mt-1 inline-flex items-center gap-1 font-mono text-[0.7rem] text-indigo-300 group-hover:underline">
                      {line ? `line at ${fmtTime(line.t_start)}` : `utterance #${p.utterance_id}`} <IconArrowRight className="h-3 w-3" />
                    </span>
                  </span>
                </button>
              )}
              {p.suggested_agent_action && (
                <p className="mt-2 text-sm leading-snug text-slate-300">
                  <span className="font-semibold text-slate-100">Agent action: </span>{p.suggested_agent_action}
                </p>
              )}
              {p.source && (
                <a href={p.source} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs text-indigo-300 hover:underline">
                  <IconLink className="h-3 w-3" /> Source: {host(p.source)}
                </a>
              )}
            </article>
          );
        })}
      </div>
    </Panel>
  );
}
