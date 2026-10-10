// The public "take a call" protocol (GET /api/config, POST /api/session, WS /ws/session/{id}).
// Type-only module: safe to import from node --test.
import type { AlertLevel, Citation, SignalName } from "../types";

/** "client": a scammer calls you (Baseline protects you). "scammer": you call the bank as Kevin.
 *  "agent" is the v1 name of "client" (old reports). */
export type Role = "client" | "scammer" | "agent";
export type Speaker = "ai" | "visitor";

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
  role: "client" | "scammer" | "random";
  scenario: string;
  voice: string;
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
  | { type: "trust"; score: number }
  | { type: "alert"; level: AlertLevel; reasons: string[]; suggested_action: string; signals: string[]; citations: Citation[] }
  | { type: "warning"; message: string; seconds_left: number }
  /** Baseline warns the client (role client). At "high" it is also spoken, see baseline_audio_*. */
  | { type: "intervention"; level: "caution" | "high"; message: string; reason_id: string }
  /** Binary frames between these two markers are Baseline's voice (to the client only), not the caller's. */
  | { type: "baseline_audio_start"; reason_id: string; text: string; sample_rate?: number }
  | { type: "baseline_audio_end"; reason_id: string }
  | { type: "action"; kind: ActionKind; message: string }
  | { type: "suspect_ack"; t: number | null }
  | { type: "call_ended"; reason: string; report_id: string; reveal: Reveal }
  | { type: "error"; message: string };

export type ClientMsg = { type: "hangup" } | { type: "ping" } | { type: "text"; text: string } | { type: "suspect" };

export type MsgOf<T extends ServerMsg["type"]> = Extract<ServerMsg, { type: T }>;

export const isClientRole = (r: Role | undefined | null) => r !== "scammer";
