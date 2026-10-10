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

  close() {
    this.stop();
    void this.ctx.close();
  }
}
