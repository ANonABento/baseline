// Gapless playback of the AI voice: 16 kHz mono int16 PCM chunks scheduled back to back
// on a Web Audio clock. The scheduling math is pure (planChunk) and unit-tested.

export interface ScheduleState {
  /** audio-clock time at which the next chunk should start; 0 = nothing queued */
  nextTime: number;
}

export interface Plan {
  startAt: number;
  state: ScheduleState;
  /** true when playback had drained and this chunk starts a new run (after the lead-in) */
  restarted: boolean;
}

/**
 * Where to start a chunk of `duration` seconds given the audio clock `now`.
 * Chunks queue back to back; if the queue has drained (underrun) we restart `lead` seconds
 * ahead of now so the first samples aren't clipped. If we've fallen more than `maxAhead`
 * seconds behind real time (e.g. a tab was throttled) we also restart, dropping the backlog.
 */
export function planChunk(s: ScheduleState, now: number, duration: number, lead = 0.08, maxAhead = 8): Plan {
  const drained = s.nextTime < now + 0.005;
  const runaway = s.nextTime - now > maxAhead;
  const startAt = drained || runaway ? now + lead : s.nextTime;
  return { startAt, state: { nextTime: startAt + duration }, restarted: drained || runaway };
}

/** int16 PCM -> float32 [-1, 1] */
export function pcm16ToFloat(buf: ArrayBuffer): Float32Array {
  const v = new Int16Array(buf, 0, Math.floor(buf.byteLength / 2));
  const out = new Float32Array(v.length);
  for (let i = 0; i < v.length; i++) out[i] = v[i] / 0x8000;
  return out;
}

export function rms(samples: Float32Array): number {
  if (!samples.length) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.sqrt(sum / samples.length);
}

/** Browser-only player. Create lazily from a user gesture (Join call) so autoplay is allowed. */
export class PcmPlayer {
  private ctx: AudioContext;
  private gain: GainNode;
  private state: ScheduleState = { nextTime: 0 };
  private live = new Set<AudioBufferSourceNode>();
  private sampleRate: number;

  constructor(sampleRate = 16000) {
    this.sampleRate = sampleRate;
    this.ctx = new AudioContext();
    this.gain = this.ctx.createGain();
    this.gain.connect(this.ctx.destination);
  }

  setSampleRate(sr: number) {
    if (sr >= 8000 && sr <= 96000) this.sampleRate = sr;
  }

  async resume() {
    if (this.ctx.state === "suspended") await this.ctx.resume();
  }

  /** Queue one chunk; returns its RMS (0..1) so callers can animate without ai_level. */
  push(buf: ArrayBuffer): number {
    const data = pcm16ToFloat(buf);
    if (!data.length) return 0;
    const ab = this.ctx.createBuffer(1, data.length, this.sampleRate);
    ab.copyToChannel(data as Float32Array<ArrayBuffer>, 0);
    const src = this.ctx.createBufferSource();
    src.buffer = ab;
    src.connect(this.gain);
    const plan = planChunk(this.state, this.ctx.currentTime, ab.duration);
    this.state = plan.state;
    src.start(plan.startAt);
    this.live.add(src);
    src.onended = () => this.live.delete(src);
    return rms(data);
  }

  /** stop_audio / barge-in: cut everything that's queued, immediately. */
  stop() {
    for (const s of this.live) {
      try {
        s.stop();
      } catch {
        /* already stopped */
      }
    }
    this.live.clear();
    this.state = { nextTime: 0 };
  }

  get playing(): boolean {
    return this.state.nextTime > this.ctx.currentTime;
  }

  /** Fade out over `ms` then cut everything queued (ducking the caller under Baseline's voice). */
  fadeStop(ms = 180) {
    const t = this.ctx.currentTime;
    this.gain.gain.cancelScheduledValues(t);
    this.gain.gain.setValueAtTime(this.gain.gain.value, t);
    this.gain.gain.linearRampToValueAtTime(0, t + ms / 1000);
    window.setTimeout(() => {
      this.stop();
      this.gain.gain.cancelScheduledValues(this.ctx.currentTime);
      this.gain.gain.setValueAtTime(1, this.ctx.currentTime);
    }, ms + 20);
  }

  get context(): AudioContext {
    return this.ctx;
  }

  close() {
    this.stop();
    void this.ctx.close();
  }
}

/**
 * Baseline's chime: two soft sine tones, a rising fourth (A5 then D6), ~0.7 s. Synthesized, no asset.
 * Calm on purpose: it should read as "your bank, stepping in", not as an alarm.
 */
export function playChime(ctx: AudioContext, volume = 0.18): void {
  const now = ctx.currentTime + 0.02;
  const out = ctx.createGain();
  out.gain.value = volume;
  out.connect(ctx.destination);
  for (const { f, at } of [
    { f: 880, at: 0 },
    { f: 1174.66, at: 0.16 },
  ]) {
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = "sine";
    o.frequency.value = f;
    g.gain.setValueAtTime(0, now + at);
    g.gain.linearRampToValueAtTime(1, now + at + 0.012);
    g.gain.exponentialRampToValueAtTime(0.001, now + at + 0.55);
    o.connect(g).connect(out);
    o.start(now + at);
    o.stop(now + at + 0.6);
  }
}

/** Browser speech for Baseline's voice when the server doesn't stream it (mock mode). */
export function speakFallback(text: string, onEnd?: () => void): boolean {
  const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
  if (!synth) return false;
  try {
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const voices = synth.getVoices().filter((v) => v.lang.startsWith("en"));
    u.voice = voices.find((v) => /samantha|serena|ava|google us english/i.test(v.name)) ?? voices[0] ?? null;
    u.rate = 1.02;
    if (onEnd) u.onend = () => onEnd();
    synth.speak(u);
    return true;
  } catch {
    return false;
  }
}
