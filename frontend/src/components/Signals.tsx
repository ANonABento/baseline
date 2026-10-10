import type { Behaviour } from "../lib/contract";
import type { SignalEvent } from "../types";

// Live behavioural signals for the analysed speaker (the human; in the demo, the scammer).
// Observations first, then hedged possible meanings. Never a verdict: model/rule scores, not calibrated.

const EVENT_LABEL: Record<string, string> = {
  verification_requested: "Asked to verify",
  refused: "Refused",
  complied_phrase: "Complied",
};

const fmt = (v: number | null | undefined, d = 1, unit = "") => (v == null ? "–" : `${v.toFixed(d)}${unit}`);
const signed = (v: number | null | undefined, d = 1, unit = "") => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(d)}${unit}`);

interface Row {
  name: string;
  value: string;
  sub?: string;
  /** 0 = within own range, 1 = notable, 2 = large */
  level: 0 | 1 | 2;
  meaning?: string;
}

function lvl(x: number | null | undefined, a: number, b: number): 0 | 1 | 2 {
  if (x == null) return 0;
  const m = Math.abs(x);
  return m >= b ? 2 : m >= a ? 1 : 0;
}

export function rowsOf(b: Behaviour | null, latest: SignalEvent | undefined): Row[] {
  const d = (latest?.details ?? {}) as { status?: string; baseline_n?: number; z?: Record<string, number> };
  const zPitch = d.status === "ok" ? d.z?.f0_median_st : undefined;
  const td = b?.tone_drift;
  const sr = b?.speech_rate;
  const h = b?.hesitation;
  const rl = b?.response_latency_s;
  const rec = b?.recovery_latency;
  return [
    {
      name: "Tone drift",
      value: zPitch != null ? `${signed(zPitch)} σ pitch` : d.status === "building_baseline" ? "learning baseline" : "–",
      sub: `trend ${signed(td?.pitch_z_per_min, 2)} σ/min · loudness ${signed(td?.loudness_z_per_min, 2)} σ/min`,
      level: lvl(zPitch ?? td?.max_abs_z, 1.5, 2.5),
      meaning: "Can reflect pressure, uncertainty, a topic change, or a noisy line.",
    },
    {
      name: "Speech rate",
      value: fmt(sr?.words_per_s_mean, 1, " w/s"),
      sub: `trend ${signed(sr?.words_per_s_trend_per_min, 2)} w/s per min`,
      level: lvl(sr?.words_per_s_trend_per_min, 0.5, 1.0),
      meaning: "Speeding up can mean urgency or a rehearsed line; slowing can mean searching for an answer.",
    },
    {
      name: "Hesitation",
      value: `${fmt(h?.fillers_per_100_words, 1)} fillers / 100 w`,
      sub: `pauses ${h?.pause_frac_mean == null ? "–" : `${Math.round(h.pause_frac_mean * 100)}%`} of speech · hedges ${fmt(b?.interaction.hedges_per_100_words, 1)} / 100 w`,
      level: lvl(h?.fillers_per_100_words, 4, 8),
      meaning: "Can mean improvising, nervousness, or simply how this person talks.",
    },
    {
      name: "Response latency",
      value: fmt(rl?.mean, 1, " s"),
      sub: rl?.n ? `max ${fmt(rl.max, 1, " s")} over ${rl.n} replies` : "after the agent speaks",
      level: lvl(rl?.max, 2, 4),
      meaning: "Long gaps after a verification question can mean the answer isn't ready.",
    },
    {
      name: "De-escalation",
      value:
        rec?.status === "recovered"
          ? `back to baseline in ${fmt(rec.latency_s, 1, " s")}`
          : rec?.status === "not_recovered_in_call"
            ? "not back to baseline yet"
            : "no large change yet",
      sub: rec?.peak_at_s != null ? `largest change at ${fmt(rec.peak_at_s, 0, " s")}` : undefined,
      level: rec?.status === "not_recovered_in_call" ? 2 : rec?.status === "recovered" ? 1 : 0,
      meaning: "How fast delivery returns to this speaker's own range after the biggest shift.",
    },
  ];
}

export function Signals({ behaviour, signals }: { behaviour: Behaviour | null; signals: SignalEvent[] }) {
  const latest = [...signals].reverse().find((s) => s.signal === "prosody");
  const rows = rowsOf(behaviour, latest);
  const ev = behaviour?.decision_events ?? [];
  const n = behaviour?.n_turns_analysed ?? 0;
  return (
    <section className="signals" aria-label="Live behavioural signals" aria-live="polite">
      <div className="signals__head">
        <span className="label">Behavioural signals · vs own baseline</span>
        <span className="label num">{n} {n === 1 ? "turn" : "turns"}</span>
      </div>
      <ul className="signals__rows">
        {rows.map((r) => (
          <li key={r.name} className={`sig sig--${r.level}`}>
            <span className="sig__name">{r.name}</span>
            <span className="sig__value num">{r.value}</span>
            {r.sub && <span className="sig__sub">{r.sub}</span>}
            {r.level > 0 && r.meaning && <span className="sig__meaning">Could mean: {r.meaning}</span>}
          </li>
        ))}
      </ul>
      <div className="signals__decisions">
        <span className="label">Decisions</span>
        {ev.length === 0 ? (
          <span className="sig__sub">none yet</span>
        ) : (
          ev.slice(-6).map((e) => (
            <span key={`${e.utterance_id}-${e.event}`} className={`chip chip--${e.event}`}>
              {EVENT_LABEL[e.event] ?? e.event} <span className="num">{Math.round(e.t)}s</span>
            </span>
          ))
        )}
      </div>
      <p className="signals__note">Signals, not a verdict. Uncalibrated; a human decides.</p>
    </section>
  );
}
