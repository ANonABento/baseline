// Mock backend: simulates queue -> call -> scripted AI lines with a fake audio level,
// transcript, signals, trust and an escalating alert. Speaks AI lines with the browser's
// speechSynthesis when available (disable with ?tts=0).
import type { AppConfig, ClientMsg, Role, ServerMsg, SessionRequest } from "./contract";
import { pickScript, SCAMMER_TRIGGERS, SCENARIOS, VOICES, type PatternSpec, type Script, type ScriptLine } from "./mockScripts";

export const MOCK_CONFIG: AppConfig = {
  roles: [
    { id: "agent", label: "You're the bank agent" },
    { id: "scammer", label: "You're the scammer" },
  ],
  scenarios: SCENARIOS,
  voices: VOICES,
  max_concurrent: 2,
  queue_length: 1,
  active_calls: 2,
  tts: "browser speechSynthesis (mock)",
  llm: { provider: "mock", model: "scripted" },
};

interface Handlers {
  onMsg: (msg: ServerMsg) => void;
  onAudio: (pcm: ArrayBuffer) => void;
  onClose: () => void;
}

const pick = <T,>(xs: T[]): T => xs[Math.floor(Math.random() * xs.length)];
const MAX_CALL_S = 180;

export class MockTransport {
  readonly id = `mock-${Date.now().toString(36)}`;
  private h: Handlers;
  private timers = new Set<number>();
  private closed = false;
  private role: Role;
  private scenario: string;
  private voice: string;
  private script: Script;
  private next = 0;
  private uid = 0;
  private t0 = 0;
  private aiBusy = false;
  private idleTimer = 0;
  // visitor speech detection on incoming PCM
  private vSpeaking = false;
  private vStart = 0;
  private vLastLoud = 0;
  private lastLevel = 0;
  private ended = false;

  constructor(req: SessionRequest, h: Handlers) {
    this.h = h;
    this.role = req.role === "random" ? pick<Role>(["agent", "scammer"]) : req.role;
    this.scenario = req.scenario === "random" ? pick(SCENARIOS).id : req.scenario;
    this.voice = req.voice === "random" ? pick(VOICES).id : req.voice;
    this.script = pickScript(this.role, this.scenario);
    this.later(250, () => this.emit({ type: "queue", position: 2, queue_length: 3, eta_s: 45 }));
    this.later(2200, () => this.emit({ type: "queue", position: 1, queue_length: 2, eta_s: 15 }));
    this.later(4200, () => this.start());
  }

  // ---------------------------------------------------------------- plumbing
  private later(ms: number, fn: () => void): number {
    const id = window.setTimeout(() => {
      this.timers.delete(id);
      if (!this.closed) fn();
    }, ms);
    this.timers.add(id);
    return id;
  }
  private emit(msg: ServerMsg) {
    if (!this.closed) this.h.onMsg(msg);
  }
  private now(): number {
    return (performance.now() - this.t0) / 1000;
  }

  // ---------------------------------------------------------------- call
  private start() {
    this.t0 = performance.now();
    this.emit({
      type: "call_started",
      session_id: this.id,
      role: this.role,
      scenario: this.scenario,
      voice: this.voice,
      customer: this.script.customer,
      audio: { sample_rate: 16000, format: "pcm_s16le" },
      max_call_s: MAX_CALL_S,
    });
    this.later(1200, () => this.aiTurn());
    this.later((MAX_CALL_S - 30) * 1000, () => this.emit({ type: "warning", message: "30 seconds left in this call.", seconds_left: 30 }));
    this.later(MAX_CALL_S * 1000, () => this.end("time_limit"));
  }

  private armIdle(ms = 7000) {
    window.clearTimeout(this.idleTimer);
    this.timers.delete(this.idleTimer);
    this.idleTimer = this.later(ms, () => this.aiTurn());
  }

  private aiTurn() {
    if (this.aiBusy || this.ended) return;
    const line = this.script.lines[this.next];
    if (!line) {
      this.end("caller_hung_up");
      return;
    }
    this.next++;
    this.aiBusy = true;
    const words = line.text.split(/\s+/).length;
    const dur = Math.max(1.6, words * 0.34);
    const tStart = this.now();
    this.emit({ type: "speaking", who: "ai", state: "start" });
    this.speak(line.text);
    const levelTimer = window.setInterval(() => {
      if (this.closed) return window.clearInterval(levelTimer);
      const t = performance.now() / 1000;
      const syll = Math.abs(Math.sin(t * 7.3)) * (0.55 + 0.45 * Math.sin(t * 2.1 + 1));
      this.emit({ type: "ai_level", rms: Math.max(0.04, Math.min(1, 0.12 + syll * 0.6 + Math.random() * 0.12)) });
    }, 60);
    this.later(dur * 1000, () => {
      window.clearInterval(levelTimer);
      this.emit({ type: "ai_level", rms: 0 });
      this.emit({ type: "speaking", who: "ai", state: "end" });
      const id = ++this.uid;
      this.emit({ type: "transcript", utterance_id: id, t_start: tStart, t_end: this.now(), text: line.text, speaker: "ai", analyzed: this.role === "agent" });
      this.aiBusy = false;
      if (this.role === "agent") this.analyze(id, line);
      // the last line is a goodbye
      if (this.next >= this.script.lines.length && this.role === "agent") this.later(2500, () => this.end("caller_hung_up"));
      else this.armIdle(this.role === "agent" ? 6500 : 12000);
    });
  }

  private analyze(id: number, line: ScriptLine) {
    let d = 450;
    for (const a of line.audio ?? []) {
      this.later((d += 180), () => this.emit({ type: "signal", utterance_id: id, signal: a.signal, score: a.score, confidence: a.confidence, reason: a.reason, details: a.details ?? {} }));
    }
    if (line.patterns?.length) this.later((d += 900), () => this.fraudSignal(id, line.patterns!));
    if (line.trust != null) this.later((d += 150), () => this.emit({ type: "trust", score: line.trust! }));
    if (line.alert) {
      const a = line.alert;
      const citations = (line.patterns ?? []).map((p) => ({ pattern_id: p.id, name: p.name, source: p.source.url }));
      this.later((d += 200), () => this.emit({ type: "alert", ...a, citations }));
    }
  }

  private fraudSignal(id: number, pats: PatternSpec[]) {
    const score = Math.max(...pats.map((p) => p.severity));
    this.emit({
      type: "signal",
      utterance_id: id,
      signal: "fraud",
      score,
      confidence: 0.85,
      reason: pats.map((p) => p.name).join("; "),
      details: {
        engine: "llm",
        model: "qwen3.5:4b (mock)",
        patterns: pats.map((p) => ({ ...p, utterance_id: id })),
      },
    });
  }

  private speak(text: string) {
    if (new URLSearchParams(location.search).get("tts") === "0") return;
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!synth) return;
    try {
      const u = new SpeechSynthesisUtterance(text);
      const voices = synth.getVoices().filter((v) => v.lang.startsWith("en"));
      const idx = VOICE_INDEX[this.voice] ?? 0;
      if (voices.length) u.voice = voices[idx % voices.length];
      u.rate = 1.05;
      synth.speak(u);
    } catch {
      /* speech is decoration in mock mode */
    }
  }

  private visitorLine(text: string, tStart: number) {
    const id = ++this.uid;
    this.emit({ type: "transcript", utterance_id: id, t_start: tStart, t_end: this.now(), text, speaker: "visitor", analyzed: this.role === "scammer" });
    if (this.role === "scammer") {
      const pats = SCAMMER_TRIGGERS.filter((t) => t.re.test(text)).map((t) => t.make(text.match(t.re)?.[0] ?? text));
      const scam = pats.length > 0;
      const spoofScore = 0.12 + Math.random() * 0.15;
      this.later(500, () => this.emit({ type: "signal", utterance_id: id, signal: "spoof", score: spoofScore, confidence: 0.6, reason: "Audio consistent with a live human voice", details: {} }));
      this.later(700, () => this.emit({ type: "signal", utterance_id: id, signal: "speaker", score: 0.64, confidence: 0.8, reason: "Voice is far from the enrolled voiceprint", details: { similarity: 0.27 } }));
      if (scam) {
        this.later(1500, () => this.fraudSignal(id, pats));
        const hi = pats.some((p) => p.severity >= 0.6);
        this.later(1700, () =>
          this.emit({
            type: "alert",
            level: hi ? "high" : "caution",
            reasons: ["Voice doesn't match enrolled customer", ...pats.map((p) => p.name)],
            suggested_action: pats[0].suggested_agent_action,
            signals: ["speaker", "fraud"],
            citations: pats.map((p) => ({ pattern_id: p.id, name: p.name, source: p.source.url })),
          }),
        );
        this.later(1600, () => this.emit({ type: "trust", score: hi ? 18 : 45 }));
      } else {
        this.later(1600, () => this.emit({ type: "trust", score: 62 }));
        this.later(1700, () => this.emit({ type: "alert", level: "caution", reasons: ["Voice doesn't match enrolled customer"], suggested_action: "Verify identity before any change.", signals: ["speaker"], citations: [] }));
      }
    }
    if (!this.aiBusy) this.later(900, () => this.aiTurn());
  }

  private end(reason: string) {
    if (this.ended) return;
    this.ended = true;
    try {
      window.speechSynthesis?.cancel();
    } catch {
      /* noop */
    }
    this.emit({ type: "stop_audio" });
    this.emit({
      type: "call_ended",
      reason,
      report_id: this.id,
      reveal: { role: this.role, scenario: this.scenario, persona_label: this.script.persona_label, voice: this.voice, tts: MOCK_CONFIG.tts },
    });
    this.later(200, () => this.close());
  }

  // ---------------------------------------------------------------- Transport
  send(msg: ClientMsg) {
    if (this.closed) return;
    if (msg.type === "hangup") this.end("visitor_hung_up");
    else if (msg.type === "text" && msg.text.trim() && this.t0) {
      this.stopAi();
      this.visitorLine(msg.text.trim(), this.now());
    }
  }

  /** Barge-in: the visitor started talking over the AI. */
  private stopAi() {
    try {
      window.speechSynthesis?.cancel();
    } catch {
      /* noop */
    }
  }

  sendPcm(pcm: ArrayBuffer) {
    if (this.closed || !this.t0 || this.ended) return;
    const v = new Int16Array(pcm);
    let sum = 0;
    for (let i = 0; i < v.length; i++) sum += v[i] * v[i];
    const level = v.length ? Math.sqrt(sum / v.length) / 32768 : 0;
    this.lastLevel = level;
    const t = this.now();
    if (level > 0.02) {
      this.vLastLoud = t;
      if (!this.vSpeaking) {
        this.vSpeaking = true;
        this.vStart = t;
        this.stopAi();
        this.emit({ type: "stop_audio" });
        this.emit({ type: "speaking", who: "visitor", state: "start" });
        window.clearTimeout(this.idleTimer);
      }
    } else if (this.vSpeaking && t - this.vLastLoud > 0.7) {
      this.vSpeaking = false;
      this.emit({ type: "speaking", who: "visitor", state: "end" });
      const secs = (this.vLastLoud - this.vStart).toFixed(1);
      this.visitorLine(`(You spoke for ${secs} s. Demo mode doesn't transcribe voice; type to test the analyzer.)`, this.vStart);
    }
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    for (const id of this.timers) window.clearTimeout(id);
    this.timers.clear();
    try {
      window.speechSynthesis?.cancel();
    } catch {
      /* noop */
    }
    this.h.onClose();
  }

  get level() {
    return this.lastLevel;
  }
}

const VOICE_INDEX: Record<string, number> = { aria: 0, dominic: 1, june: 2, rafael: 3 };
