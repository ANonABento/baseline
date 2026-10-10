// Transcript margin notes: map signals + fraud evidence onto transcript lines and spans.
// Pure module (tests/notes.test.ts).
import { FIRE_CONFIDENCE, SEVERITY_RANK, type EvidenceItem } from "../analysis.ts";
import type { AlertEvent, Severity, SignalEvent, SignalName, TranscriptEvent } from "../types.ts";

export type Tier = "noted" | "watch" | "flag";
export const TIER_RANK: Record<Tier, number> = { noted: 1, watch: 2, flag: 3 };
export const TIER_GLYPH: Record<Tier, string> = { noted: "◇", watch: "◆", flag: "■" };
export const TIER_LABEL: Record<Tier, string> = { noted: "Noted", watch: "Watch", flag: "Flag" };

export interface Note {
  id: string;
  utterance_id: number;
  tier: Tier;
  kind: SignalName;
  title: string;
  body: string;
  quote: string;
  /** [start, end) character offsets into the line text, or null when the quote isn't locatable */
  span: [number, number] | null;
  sayThis?: string;
  source?: string;
  sourceUrl?: string;
  score?: number;
}

const AUDIO_TITLES: Record<Exclude<SignalName, "fraud">, Record<"watch" | "flag", string>> = {
  speaker: { watch: "Voice drifting from enrolled print", flag: "Voice doesn't match enrolled customer" },
  spoof: { watch: "Possible synthetic artifacts", flag: "Synthetic voice" },
  prosody: { watch: "Pace and pitch shift", flag: "Pressure above caller's baseline" },
};

export function severityTier(sev: Severity): Tier {
  return sev === "high" ? "flag" : sev === "medium" ? "watch" : "noted";
}

/** Tier an audio signal reaches; prosody is a soft signal and caps one tier lower. */
export function audioTier(s: Pick<SignalEvent, "signal" | "score" | "confidence">): Tier | null {
  if (s.confidence < FIRE_CONFIDENCE) return null;
  const base: Tier | null = s.score >= 0.5 ? "flag" : s.score >= 0.25 ? "watch" : null;
  if (!base || s.signal !== "prosody") return base;
  return base === "flag" ? "watch" : "noted";
}

const normChars = (s: string) => s.toLowerCase().replace(/[’‘]/g, "'").replace(/[“”]/g, '"');

/**
 * Locate `quote` inside `text` (case / curly-quote insensitive). Falls back to the longest
 * word-prefix of the quote (at least 3 words) so lightly paraphrased quotes still underline.
 */
export function findSpan(text: string, quote: string): [number, number] | null {
  const q = normChars(quote).trim().replace(/^["'.…\s]+|["'.…,;:!?\s]+$/g, "");
  if (!q) return null;
  const t = normChars(text);
  const i = t.indexOf(q);
  if (i >= 0) return [i, i + q.length];
  const words = q.split(/\s+/);
  for (let n = words.length - 1; n >= 3; n--) {
    const sub = words.slice(0, n).join(" ");
    const j = t.indexOf(sub);
    if (j >= 0) return [j, j + sub.length];
  }
  return null;
}

/** Build every margin note for the call, grouped by line. */
export function buildNotes(lines: TranscriptEvent[], signals: SignalEvent[], evidence: EvidenceItem[]): Note[] {
  const byId = new Map(lines.map((l) => [l.utterance_id, l]));
  const notes: Note[] = [];

  for (const e of evidence) {
    const line = byId.get(e.utterance_id);
    notes.push({
      id: `fraud:${e.id}`,
      utterance_id: e.utterance_id,
      tier: severityTier(e.severity),
      kind: "fraud",
      title: e.name,
      body: e.suggested_agent_action,
      quote: e.quote,
      span: line ? findSpan(line.text, e.quote) : null,
      sayThis: e.say_this,
      source: e.source || undefined,
      sourceUrl: e.source_url ?? (/^https?:\/\//.test(e.source) ? e.source : undefined),
    });
  }

  const lanes: SignalName[] = evidence.length ? ["speaker", "spoof", "prosody"] : ["speaker", "spoof", "prosody", "fraud"];
  for (const lane of lanes) {
    let highest = 0;
    const evs = signals.filter((s) => s.signal === lane).sort((a, b) => a.utterance_id - b.utterance_id);
    for (const s of evs) {
      const tier = lane === "fraud" ? (s.confidence >= FIRE_CONFIDENCE && s.score >= 0.5 ? "flag" : null) : audioTier(s);
      if (!tier || TIER_RANK[tier] <= highest) continue;
      highest = TIER_RANK[tier];
      const title = lane === "fraud" ? "Fraud pattern" : AUDIO_TITLES[lane][tier === "flag" ? "flag" : "watch"];
      const simV = s.details?.similarity;
      const sim = typeof simV === "number" && !/similarity/i.test(s.reason) ? ` Similarity ${simV.toFixed(2)}.` : "";
      notes.push({
        id: `${lane}:${s.utterance_id}:${tier}`,
        utterance_id: s.utterance_id,
        tier,
        kind: lane,
        title,
        body: `${s.reason}${sim}`.trim(),
        quote: "",
        span: null,
        score: s.score,
      });
    }
  }

  return notes.sort((a, b) => a.utterance_id - b.utterance_id || TIER_RANK[b.tier] - TIER_RANK[a.tier]);
}

export function notesByLine(notes: Note[]): Map<number, Note[]> {
  const m = new Map<number, Note[]>();
  for (const n of notes) m.set(n.utterance_id, [...(m.get(n.utterance_id) ?? []), n]);
  return m;
}

export function worstTier(notes: Note[]): Tier | null {
  let best: Tier | null = null;
  for (const n of notes) if (!best || TIER_RANK[n.tier] > TIER_RANK[best]) best = n.tier;
  return best;
}

export interface TextSegment {
  text: string;
  start: number;
  end: number;
  noteIds: string[];
  tier: Tier | null;
}

/** Split a line into segments at every span boundary, so overlapping spans render cleanly. */
export function segmentText(text: string, notes: Note[]): TextSegment[] {
  const spans = notes.filter((n) => n.span) as (Note & { span: [number, number] })[];
  const cuts = new Set<number>([0, text.length]);
  for (const n of spans) {
    cuts.add(Math.max(0, Math.min(text.length, n.span[0])));
    cuts.add(Math.max(0, Math.min(text.length, n.span[1])));
  }
  const points = [...cuts].sort((a, b) => a - b);
  const out: TextSegment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [start, end] = [points[i], points[i + 1]];
    if (end <= start) continue;
    const covering = spans.filter((n) => n.span[0] <= start && n.span[1] >= end);
    out.push({ text: text.slice(start, end), start, end, noteIds: covering.map((n) => n.id), tier: worstTier(covering) });
  }
  return out;
}

export interface Spike {
  noteId: string;
  utterance_id: number;
  /** 0..1 along the timeline */
  x: number;
  tier: Tier;
}

/** One spike per note, at the middle of its line on a `duration`-second axis. */
export function spikesFromNotes(notes: Note[], lines: TranscriptEvent[], duration: number): Spike[] {
  const byId = new Map(lines.map((l) => [l.utterance_id, l]));
  const out: Spike[] = [];
  for (const n of notes) {
    const l = byId.get(n.utterance_id);
    if (!l || duration <= 0) continue;
    const mid = (l.t_start + Math.max(l.t_end, l.t_start)) / 2;
    out.push({ noteId: n.id, utterance_id: n.utterance_id, x: Math.min(1, Math.max(0, mid / duration)), tier: n.tier });
  }
  return out;
}

export type VerdictLevel = "clear" | "watching" | "alert";

export interface Verdict {
  level: VerdictLevel;
  agreeing: number;
  headline: string;
  sayThis: string | null;
  reasons: string[];
}

/** The evidence item whose script line to surface: most severe, and among equals the most recent. */
export function topEvidence(evidence: EvidenceItem[], needSayThis = false): EvidenceItem | undefined {
  return [...evidence]
    .filter((e) => !needSayThis || e.say_this)
    .sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.first_utterance_id - a.first_utterance_id)[0];
}

/** What the verdict strip shows: the backend alert, with the best "say this" line attached. */
export function verdictOf(alert: AlertEvent | null, notes: Note[], evidence: EvidenceItem[]): Verdict {
  const level: VerdictLevel = alert?.level === "high" ? "alert" : alert?.level === "caution" ? "watching" : "clear";
  const flaggedLanes = new Set(notes.filter((n) => n.tier === "flag").map((n) => n.kind));
  const agreeing = alert?.signals?.length ? new Set(alert.signals).size : flaggedLanes.size;
  const top = topEvidence(evidence, true);
  const sayThis = level === "clear" ? null : top?.say_this || alert?.suggested_action || null;
  const headline =
    level === "alert" ? "Likely fraud. Don't move money." : level === "watching" ? "Something's off. Slow down." : "Nothing unusual so far.";
  return { level, agreeing, headline, sayThis, reasons: alert?.reasons ?? [] };
}
