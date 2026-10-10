// Mirrors backend/events.py
export type SignalName = "speaker" | "spoof" | "prosody" | "fraud";
export type AlertLevel = "none" | "caution" | "high";

export interface TranscriptEvent {
  type: "transcript";
  utterance_id: number;
  t_start: number;
  t_end: number;
  text: string;
}

export interface SignalEvent {
  type: "signal";
  utterance_id: number;
  signal: SignalName;
  score: number; // risk 0-1
  confidence: number; // 0-1
  reason: string;
  details: Record<string, unknown>;
  latency_ms: number;
}

export interface TrustEvent {
  type: "trust";
  utterance_id: number;
  score: number; // 0-100 smoothed
  raw: number;
  components: Record<string, number>;
}

export interface Citation {
  pattern_id: string;
  name: string;
  source: string;
}

export interface AlertEvent {
  type: "alert";
  level: AlertLevel;
  reasons: string[];
  suggested_action: string;
  signals: string[];
  citations: Citation[];
}

export interface StatusEvent {
  type: "status";
  state: string;
  message: string;
  clip: string | null;
}

export type ServerEvent = TranscriptEvent | SignalEvent | TrustEvent | AlertEvent | StatusEvent;

export interface Clip {
  name: string;
  duration_s: number | null;
  has_transcript: boolean;
}

export interface Customer {
  id: string;
  name: string;
  enrolled: boolean;
  voiceprint: string;
  phone_on_file: string;
  member_since: string;
  segment: string;
}

// ---------------------------------------------------------------- fraud evidence contract
// Shape of `details` on a `fraud` SignalEvent (agreed with the backend). Every field is
// optional on the wire: older backends send `patterns` as a list of ids plus `citations`
// and `matched_phrases`; the frontend tolerates both (see analysis.ts).
export type Severity = "low" | "medium" | "high";

export interface FraudPatternEvidence {
  id: string;
  name: string;
  severity: Severity;
  quote: string;
  utterance_id: number;
  source: string;
  suggested_agent_action: string;
}

export interface FraudEvidenceDetails {
  patterns?: FraudPatternEvidence[] | string[];
  engine?: "llm" | "keywords" | string;
  model?: string | null;
  // legacy fields (pre-contract backend)
  citations?: Citation[];
  matched_phrases?: Record<string, string[]>;
  suggested_action?: string;
  method?: string;
}
