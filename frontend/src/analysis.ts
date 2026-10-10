// Pure, framework-free logic behind the dashboard: evidence merging, transcript trigger
// mapping and timeline layout. Kept dependency-free (type-only imports) so it runs under
// `node --test` with native type stripping (see tests/analysis.test.ts).
import type {
  FraudEvidenceDetails,
  FraudPatternEvidence,
  Severity,
  SignalEvent,
  SignalName,
  TranscriptEvent,
} from "./types";

// Mirrors backend fusion.py: a signal "fires" at score >= 0.5 with confidence >= 0.3.
export const FIRE_SCORE = 0.5;
export const FIRE_CONFIDENCE = 0.3;
export const WATCH_SCORE = 0.25;

export type Tone = "none" | "ok" | "watch" | "flag";
export const TONE_RANK: Record<Tone, number> = { none: 0, ok: 1, watch: 2, flag: 3 };
export const SEVERITY_RANK: Record<Severity, number> = { low: 1, medium: 2, high: 3 };

export const LANES: SignalName[] = ["speaker", "spoof", "fraud", "prosody"];
export const SIGNAL_LABEL: Record<SignalName, string> = {
  speaker: "Voice match",
  spoof: "Synthetic voice",
  fraud: "Fraud pattern",
  prosody: "Pressure",
};

export function toneOf(s: { score: number; confidence: number }): Tone {
  if (!s.confidence) return "none";
  if (s.score >= FIRE_SCORE) return "flag";
  if (s.score >= WATCH_SCORE) return "watch";
  return "ok";
}

export function isFired(s: { score: number; confidence: number }): boolean {
  return s.score >= FIRE_SCORE && s.confidence >= FIRE_CONFIDENCE;
}

export function worstTone(tones: Tone[]): Tone {
  return tones.reduce<Tone>((a, b) => (TONE_RANK[b] > TONE_RANK[a] ? b : a), "none");
}

export function severityTone(sev: Severity): Tone {
  return sev === "low" ? "watch" : "flag";
}

// ---------------------------------------------------------------- evidence

export interface EvidenceItem extends FraudPatternEvidence {
  /** utterance where this pattern first appeared */
  first_utterance_id: number;
  /** utterance of the fraud signal that last updated this pattern */
  updated_utterance_id: number;
}

export interface EvidenceState {
  items: EvidenceItem[];
  engine: string | null;
  model: string | null;
}

export const EMPTY_EVIDENCE: EvidenceState = { items: [], engine: null, model: null };

const SEVERITIES: Severity[] = ["low", "medium", "high"];
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const norm = (s: string) => s.toLowerCase().replace(/['’]/g, "");

function severityFromScore(score: number): Severity {
  return score >= 0.7 ? "high" : score >= 0.4 ? "medium" : "low";
}

/** First utterance (by id) whose text contains any of `phrases` (case/apostrophe-insensitive). */
export function findUtterance(transcript: TranscriptEvent[], phrases: string[]): TranscriptEvent | undefined {
  const needles = phrases.map(norm).filter(Boolean);
  if (!needles.length) return undefined;
  return [...transcript]
    .sort((a, b) => a.utterance_id - b.utterance_id)
    .find((t) => needles.some((n) => norm(t.text).includes(n)));
}

/**
 * Extract pattern evidence from one fraud SignalEvent. Supports the agreed contract
 * (`details.patterns` = objects) and the legacy shape (`patterns` = ids, plus `citations`,
 * `matched_phrases`, `suggested_action`). For legacy events the quote/utterance is recovered
 * by locating a matched phrase in the transcript.
 */
export function patternsFromSignal(ev: SignalEvent, transcript: TranscriptEvent[] = []): FraudPatternEvidence[] {
  if (ev.signal !== "fraud") return [];
  const d = (ev.details ?? {}) as FraudEvidenceDetails;
  const raw = Array.isArray(d.patterns) ? d.patterns : [];
  const out: FraudPatternEvidence[] = [];
  const citations = Array.isArray(d.citations) ? d.citations : [];
  for (const p of raw as unknown[]) {
    if (p && typeof p === "object") {
      const o = p as Record<string, unknown>;
      const id = str(o.id);
      if (!id) continue;
      const sev = SEVERITIES.includes(o.severity as Severity) ? (o.severity as Severity) : severityFromScore(ev.score);
      const cit = citations.find((c) => c.pattern_id === id);
      out.push({
        id,
        name: str(o.name) || cit?.name || id,
        severity: sev,
        quote: str(o.quote),
        utterance_id: typeof o.utterance_id === "number" ? o.utterance_id : ev.utterance_id,
        source: str(o.source) || cit?.source || "",
        suggested_agent_action: str(o.suggested_agent_action) || str(d.suggested_action),
      });
    } else if (typeof p === "string" && p) {
      const cit = citations.find((c) => c.pattern_id === p);
      const phrases = d.matched_phrases?.[p] ?? [];
      const line = findUtterance(transcript, phrases);
      out.push({
        id: p,
        name: cit?.name || p.replace(/_/g, " "),
        severity: severityFromScore(ev.score),
        quote: line?.text ?? (phrases.length ? phrases.map((x) => `"${x}"`).join(", ") : ""),
        utterance_id: line?.utterance_id ?? ev.utterance_id,
        source: cit?.source || "",
        suggested_agent_action: str(d.suggested_action),
      });
    }
  }
  return out;
}

/** Merge one fraud SignalEvent into the evidence list: dedupe by id, keep the latest quote. */
export function mergeEvidence(prev: EvidenceState, ev: SignalEvent, transcript: TranscriptEvent[] = []): EvidenceState {
  if (ev.signal !== "fraud") return prev;
  const d = (ev.details ?? {}) as FraudEvidenceDetails;
  const engine = str(d.engine) || str(d.method) || prev.engine;
  const model = typeof d.model === "string" ? d.model : prev.model;
  const byId = new Map(prev.items.map((i) => [i.id, i]));
  for (const p of patternsFromSignal(ev, transcript)) {
    const old = byId.get(p.id);
    if (!old) {
      byId.set(p.id, { ...p, first_utterance_id: p.utterance_id, updated_utterance_id: ev.utterance_id });
      continue;
    }
    byId.set(p.id, {
      ...old,
      name: p.name || old.name,
      // severity only escalates within a call
      severity: SEVERITY_RANK[p.severity] >= SEVERITY_RANK[old.severity] ? p.severity : old.severity,
      quote: p.quote || old.quote,
      utterance_id: p.quote ? p.utterance_id : old.utterance_id,
      source: p.source || old.source,
      suggested_agent_action: p.suggested_agent_action || old.suggested_agent_action,
      first_utterance_id: Math.min(old.first_utterance_id, p.utterance_id),
      updated_utterance_id: ev.utterance_id,
    });
  }
  const items = [...byId.values()].sort(
    (a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || a.first_utterance_id - b.first_utterance_id,
  );
  return { items, engine: engine || null, model: model ?? null };
}

// ---------------------------------------------------------------- transcript triggers

export interface LineTrigger {
  signal: SignalName;
  tone: Tone;
  label: string;
  reason: string;
  patternId?: string;
}

/**
 * Which transcript lines triggered a signal.
 * - fraud: each evidence pattern is anchored to its quoted utterance.
 * - speaker/spoof/prosody: the utterance where the signal *started* firing (onset), so a
 *   signal that stays red for the whole call marks one line, not every line.
 * - fraud with no pattern evidence: onset rule as well.
 */
export function lineTriggers(signals: SignalEvent[], evidence: EvidenceItem[]): Map<number, LineTrigger[]> {
  const out = new Map<number, LineTrigger[]>();
  const add = (id: number, t: LineTrigger) => out.set(id, [...(out.get(id) ?? []), t]);

  for (const e of evidence) {
    add(e.utterance_id, {
      signal: "fraud",
      tone: severityTone(e.severity),
      label: e.name,
      reason: `${e.severity.toUpperCase()} severity fraud pattern.${e.suggested_agent_action ? ` ${e.suggested_agent_action}` : ""}`,
      patternId: e.id,
    });
  }
  const lanes = LANES.filter((l) => l !== "fraud" || evidence.length === 0);
  for (const lane of lanes) {
    const evs = signals.filter((s) => s.signal === lane).sort((a, b) => a.utterance_id - b.utterance_id);
    let was = false;
    for (const s of evs) {
      const now = isFired(s);
      if (now && !was) add(s.utterance_id, { signal: lane, tone: "flag", label: SIGNAL_LABEL[lane], reason: s.reason });
      was = now;
    }
  }
  return out;
}

// ---------------------------------------------------------------- timeline

export interface TimelineSegment {
  utterance_id: number;
  /** fractions of the axis, 0..1 */
  x0: number;
  x1: number;
  text: string;
  tone: Tone;
}

export interface TimelineMarker {
  key: string;
  lane: SignalName;
  utterance_id: number;
  /** center of the utterance, fraction 0..1 */
  x: number;
  t: number;
  tone: Tone;
  score: number;
  confidence: number;
  reason: string;
  /** fraud patterns anchored at this utterance */
  patterns: string[];
}

export interface TimelineModel {
  duration: number;
  segments: TimelineSegment[];
  markers: TimelineMarker[];
}

/**
 * Lay out utterances and per-signal markers on a shared time axis. Signals whose utterance
 * has no transcript yet (audio detectors can finish before STT) are omitted until it arrives.
 * The axis is at least `minDuration` seconds so early markers don't stretch across the bar.
 */
export function buildTimeline(
  transcript: TranscriptEvent[],
  signals: SignalEvent[],
  evidence: EvidenceItem[] = [],
  minDuration = 30,
): TimelineModel {
  const end = transcript.reduce((m, t) => Math.max(m, t.t_end), 0);
  const duration = Math.max(minDuration, Math.ceil(end / 5) * 5 + (end > 0 ? 2 : 0));
  const byId = new Map(transcript.map((t) => [t.utterance_id, t]));
  const frac = (t: number) => Math.min(1, Math.max(0, t / duration));

  const triggers = lineTriggers(signals, evidence);
  const segments: TimelineSegment[] = [...transcript]
    .sort((a, b) => a.t_start - b.t_start)
    .map((t) => ({
      utterance_id: t.utterance_id,
      x0: frac(t.t_start),
      x1: frac(Math.max(t.t_end, t.t_start)),
      text: t.text,
      tone: worstTone((triggers.get(t.utterance_id) ?? []).map((x) => x.tone)),
    }));

  const markers: TimelineMarker[] = [];
  for (const s of signals) {
    const t = byId.get(s.utterance_id);
    if (!t) continue;
    const tone = toneOf(s);
    if (tone === "none") continue;
    const mid = (t.t_start + t.t_end) / 2;
    markers.push({
      key: `${s.signal}-${s.utterance_id}`,
      lane: s.signal,
      utterance_id: s.utterance_id,
      x: frac(mid),
      t: mid,
      tone,
      score: s.score,
      confidence: s.confidence,
      reason: s.reason,
      patterns: s.signal === "fraud" ? evidence.filter((e) => e.utterance_id === s.utterance_id).map((e) => e.name) : [],
    });
  }
  // one marker per (lane, utterance): the latest event wins
  const dedup = new Map(markers.map((m) => [m.key, m]));
  return { duration, segments, markers: [...dedup.values()].sort((a, b) => a.x - b.x) };
}

export function fmtTime(s: number): string {
  const v = Math.max(0, Math.floor(s));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
}
