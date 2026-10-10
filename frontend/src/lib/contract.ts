// The public "take a call" protocol (GET /api/config, POST /api/session, WS /ws/session/{id}).
// Type-only module: safe to import from node --test.
import type { AlertLevel, Citation, SignalName } from "../types";

/** "client": a scammer calls you (Baseline protects you). "scammer": you call the bank as Kevin.
 *  "candidate": pressure simulation, you are the bank agent. "agent" is the v1 name of "client" (old reports). */
export type Role = "client" | "scammer" | "agent" | "candidate";
export type Speaker = "ai" | "visitor";
/** Keyword-detected phrases in the candidate's turn (not verdicts). */
export type DecisionKind = "verification_requested" | "refused" | "complied_phrase" | "escalated" | "offered_alternative" | "overpromised";

export interface Option {
  id: string;
  label: string;
}

export interface ScenarioOption extends Option {
  /** which visitor role the scenario belongs to (absent on old backends) */
  role?: "client" | "scammer";
  brief?: string;
}

export interface AppConfig {
  roles: Option[] | string[];
  scenarios: ScenarioOption[];
  voices: Option[];
  max_concurrent: number;
  queue_length: number;
  active_calls: number;
  tts: string;
  llm: { provider: string; model: string | null };
  caller_llm?: { provider: string; model: string | null };
  customer?: { id: string; name: string; account_mask: string };
}

export interface SessionRequest {
  role: "client" | "scammer" | "candidate" | "random";
  scenario: string;
  voice: string;
  /** opt in to saving the visitor's mic in the report audio (the AI caller is always saved) */
  record_audio?: boolean;
}

/** Report audio: stereo WAV, left = AI caller, right = visitor (null when not recorded). t=0 is the transcript origin. */
export interface ReportAudio {
  url: string;
  duration_s: number;
  channels: { left: "ai"; right: "visitor" | null };
}

export interface SessionResponse {
  session_id: string;
  ws_url: string;
}

export interface Customer {
  id: string;
  name: string;
  account_mask: string;
  enrolled: boolean;
}

export type ActionKind = "family_alert" | "bank_hold";

export interface YouVsBaseline {
  visitor_flag_t: number | null;
  baseline_flag_t: number | null;
  baseline_high_t?: number | null;
  interventions?: number;
  actions?: string[];
}

export interface Reveal {
  role: Role;
  scenario: string;
  persona_label: string;
  voice: string;
  tts: string;
  summary?: string;
  you_vs_baseline?: YouVsBaseline;
}

export type ServerMsg =
  | { type: "queue"; position: number; queue_length: number; eta_s: number }
  | {
      type: "call_started";
      session_id: string;
      role: Role;
      scenario: string;
      voice: string;
      customer: Customer;
      audio: { sample_rate: number; format: string };
      max_call_s: number;
      scenario_label?: string | null;
      /** who the visitor is on this call, e.g. "Kevin", "Kevin's grandparent", "Posing as Kevin" */
      visitor_as?: string;
      /** role scammer: the visitor's cheat sheet */
      agenda?: Agenda | null;
    }
  | { type: "speaking"; who: Speaker; state: "start" | "end" }
  | { type: "ai_level"; rms: number }
  | { type: "stop_audio" }
  | { type: "transcript"; utterance_id: number; t_start: number; t_end: number; text: string; speaker: Speaker; analyzed: boolean }
  | {
      type: "signal";
      utterance_id: number;
      signal: SignalName;
      score: number;
      confidence: number;
      reason: string;
      details: Record<string, unknown>;
    }
  | { type: "pressure"; level: number; utterance_id: number; t: number }
  | { type: "decision"; event: DecisionKind; utterance_id: number; t: number }
  | { type: "trust"; score: number }
  | ({ type: "behaviour"; t: number } & Behaviour)
  | { type: "alert"; level: AlertLevel; reasons: string[]; suggested_action: string; signals: string[]; citations: Citation[] }
  | { type: "warning"; message: string; seconds_left: number }
  /** Baseline warns the client (role client). At "high" it is also spoken, see baseline_audio_*. */
  | { type: "intervention"; level: "caution" | "high"; message: string; reason_id: string; to?: "visitor" | "victim" }
  /** Binary frames between these two markers are Baseline's voice (to the client only), not the caller's. */
  | { type: "baseline_audio_start"; reason_id: string; text: string; sample_rate?: number }
  | { type: "baseline_audio_end"; reason_id: string }
  | { type: "action"; kind: ActionKind; message: string }
  | { type: "suspect_ack"; t: number | null }
  | { type: "call_ended"; reason: string; report_id: string; reveal: Reveal }
  | { type: "error"; message: string };

/** Session behavioural signals for the analysed speaker so far (backend detectors/session_signals.py). */
export interface Behaviour {
  n_turns_analysed: number;
  n_turns_with_baseline: number;
  calibration_status: string;
  tone_drift: { pitch_z_per_min: number | null; loudness_z_per_min: number | null; max_abs_z: number };
  speech_rate: { words_per_s_mean: number | null; words_per_s_trend_per_min: number | null };
  hesitation: { fillers_per_100_words: number | null; pause_frac_mean: number | null };
  response_latency_s: { mean: number | null; max: number | null; n: number };
  recovery_latency: { status: string; peak_at_s?: number; latency_s?: number | null };
  interaction: {
    talk_over_count: number;
    talk_time_share: number | null;
    mean_turn_s: number | null;
    hedges_per_100_words: number | null;
    verification_attempts: number;
    refusals: number;
    compliance_phrases: number;
  };
  decision_events: { t: number; utterance_id: number; event: string }[];
}

export interface Agenda {
  target: { name: string; profile: string };
  goal: string;
  cover_story: string;
  steps: string[];
  lines: string[];
  objections: { they_say: string; you_say: string }[];
  watch: string[];
}

export type ClientMsg = { type: "hangup" } | { type: "ping" } | { type: "text"; text: string } | { type: "suspect" } | { type: "ptt"; state: "down" | "up" };

export type MsgOf<T extends ServerMsg["type"]> = Extract<ServerMsg, { type: T }>;

export const isClientRole = (r: Role | undefined | null) => r !== "scammer";
