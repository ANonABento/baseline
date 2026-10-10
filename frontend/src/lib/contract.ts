// The public "take a call" protocol (GET /api/config, POST /api/session, WS /ws/session/{id}).
// Type-only module: safe to import from node --test.
import type { AlertLevel, Citation, SignalName } from "../types";

export type Role = "agent" | "scammer";
export type Speaker = "ai" | "visitor";

export interface Option {
  id: string;
  label: string;
}

export interface AppConfig {
  roles: Option[] | string[];
  scenarios: Option[];
  voices: Option[];
  max_concurrent: number;
  queue_length: number;
  active_calls: number;
  tts: string;
  llm: { provider: string; model: string };
}

export interface SessionRequest {
  role: Role | "random";
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
  | {
      type: "call_ended";
      reason: string;
      report_id: string;
      reveal: { role: Role; scenario: string; persona_label: string; voice: string; tts: string };
    }
  | { type: "error"; message: string };

export type ClientMsg = { type: "hangup" } | { type: "ping" } | { type: "text"; text: string };

export type MsgOf<T extends ServerMsg["type"]> = Extract<ServerMsg, { type: T }>;
