// Digital Twin view-model: a running model of the person on the call, derived from the session state.
// Pure (no DOM): unit-tested under node --test. Wording rule: "change vs this person's earlier delivery",
// never stress, lying, honesty or skill. calibration_status is "not_established" for every number here.
import type { DecisionKind } from "./contract.ts";
import type { SessionState } from "./session.ts";

export const BASELINE_N = 3;
export const Z_FIRE = 2.5; // same threshold as backend voice_state.Z_FIRE

export const Z_LABEL: Record<string, string> = {
  f0_median_st: "Pitch",
  f0_std_st: "Pitch spread",
  rms_db: "Loudness",
  rate_proxy: "Speech rate",
  pause_frac: "Pausing",
};

export const DECISION_LABEL: Record<DecisionKind, string> = {
  verification_requested: "Asked to verify",
  refused: "Refused",
  complied_phrase: "Compliance phrase",
  escalated: "Escalated",
  offered_alternative: "Offered an alternative",
  overpromised: "Promised an outcome",
};

export interface TwinTurn {
  utterance_id: number;
  t: number;
  t_end: number;
  words: number;
  /** words per second from transcript timing; null for typed turns (no duration) */
  wps: number | null;
  /** seconds from the AI caller finishing to this turn starting; null if the person spoke first / typed */
  latency_s: number | null;
  status: "ok" | "building_baseline" | "insufficient_evidence" | "none";
  change: number | null;
  maxAbsZ: number | null;
  pauseFrac: number | null;
  /** scripted pressure level of the most recent AI turn before this one */
  pressure: number | null;
}

export interface TwinView {
  baselineN: number;
  baselineReady: boolean;
  turns: TwinTurn[];
  latest: TwinTurn | null;
  z: Record<string, number> | null;
  markers: string[];
  pressureNow: number | null;
  decisions: { t: number; utterance_id: number; event: DecisionKind }[];
  emotion: { label: string; p: number }[] | null;
  /** fine-tuned model: P(high arousal) and which input it used; null when the model is off */
  arousal: { high: number; mode: string } | null;
  emotionModel: string | null;
}

type Obj = Record<string, unknown>;

export function twinView(s: Pick<SessionState, "lines" | "signals" | "pressure" | "decisions">, person: "visitor" | "ai" = "visitor"): TwinView {
  const prosody = new Map<number, Obj>();
  for (const g of s.signals) if (g.signal === "prosody") prosody.set(g.utterance_id, g.details as Obj);
  const lines = [...s.lines].sort((a, b) => a.t_start - b.t_start);
  const pressureAt = [...s.pressure].sort((a, b) => a.t - b.t);
  const turns: TwinTurn[] = [];
  for (const l of lines) {
    if (l.speaker !== person) continue; // scammer role: you; client role: the AI caller
    const d = prosody.get(l.utterance_id) ?? {};
    const z = (d.z ?? null) as Record<string, number> | null;
    const dur = l.t_end - l.t_start;
    const prev = [...lines].reverse().find((o) => o.t_end <= l.t_start && o.utterance_id !== l.utterance_id);
    const press = [...pressureAt].reverse().find((p) => p.t <= l.t_start);
    const words = l.text.trim().split(/\s+/).filter(Boolean).length;
    turns.push({
      utterance_id: l.utterance_id,
      t: l.t_start,
      t_end: l.t_end,
      words,
      wps: dur > 0.2 ? words / dur : null,
      latency_s: prev && prev.speaker !== person ? Math.round((l.t_start - prev.t_end) * 100) / 100 : null,
      status: ((d.status as TwinTurn["status"]) ?? "none"),
      change: typeof d.delivery_change === "number" ? d.delivery_change : null,
      maxAbsZ: z ? Math.max(...Object.values(z).map(Math.abs)) : null,
      pauseFrac: typeof (d.features as Obj | undefined)?.pause_frac === "number" ? ((d.features as Obj).pause_frac as number) : null,
      pressure: press?.level ?? null,
    });
  }
  const withD = [...turns].reverse().find((t) => t.status !== "none");
  const dLatest = withD ? prosody.get(withD.utterance_id) ?? {} : {};
  const baselineN = Math.min(
    BASELINE_N,
    Math.max(0, ...[...prosody.values()].map((d) => (typeof d.baseline_n === "number" ? d.baseline_n : d.status === "ok" ? BASELINE_N : 0))),
  );
  const probs = ((dLatest.emotion_estimate as Obj | null)?.probs ?? null) as Record<string, number> | null;
  return {
    baselineN,
    baselineReady: baselineN >= BASELINE_N,
    turns,
    latest: withD ?? null,
    z: withD?.status === "ok" ? ((dLatest.z as Record<string, number>) ?? null) : null,
    markers: withD?.status === "ok" ? (((dLatest.delivery_markers as string[]) ?? []).slice(0, 3)) : [],
    pressureNow: pressureAt.at(-1)?.level ?? null,
    decisions: [...s.decisions].sort((a, b) => a.t - b.t),
    arousal: ((dLatest.segnet as Obj | undefined)?.arousal as Record<string, number> | undefined)?.high != null
      ? { high: ((dLatest.segnet as Obj).arousal as Record<string, number>).high, mode: String((dLatest.segnet as Obj).mode ?? "") }
      : null,
    emotionModel: typeof (dLatest.emotion_estimate as Obj | null)?.model === "string" ? ((dLatest.emotion_estimate as Obj).model as string) : null,
    emotion: probs
      ? Object.entries(probs).map(([label, p]) => ({ label, p })).sort((a, b) => b.p - a.p).slice(0, 3)
      : null,
  };
}

/** Delivery change (0..1) by scripted pressure level, from per-turn z (mean of max |z|). */
export function changeByPressure(turns: TwinTurn[]): { level: number; mean: number; n: number }[] {
  const by = new Map<number, number[]>();
  for (const t of turns) if (t.pressure != null && t.maxAbsZ != null) by.set(t.pressure, [...(by.get(t.pressure) ?? []), t.maxAbsZ]);
  return [...by.entries()].sort((a, b) => a[0] - b[0]).map(([level, v]) => ({ level, mean: v.reduce((a, b) => a + b, 0) / v.length, n: v.length }));
}
