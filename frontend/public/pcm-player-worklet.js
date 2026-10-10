// AudioWorklet: gapless playback of the AI voice. 16 kHz float chunks go into one ring buffer
// and are resampled continuously to the context rate, so there are no per-chunk seams (the old
// one-AudioBufferSourceNode-per-50ms-frame approach clicked at every boundary). Underruns and
// stops fade over ~5 ms instead of cutting mid-waveform.
class PcmPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.cap = 16000 * 60; // 60 s of source audio
    this.buf = new Float32Array(this.cap);
    this.w = 0; // samples written (total)
    this.r = 0; // fractional read position (total)
    this.srcRate = 16000;
    this.playing = false;
    this.env = 0; // fade envelope 0..1
    this.last = 0; // last interpolated sample (held while fading out)
    this.waited = 0; // output samples spent waiting to prebuffer
    this.prebuffer = 0.06; // seconds buffered before (re)starting
    this.fadeStep = 1 / (0.005 * sampleRate);
    this.port.onmessage = (e) => {
      const m = e.data;
      if (m.type === "pcm") this.write(m.data);
      else if (m.type === "rate") this.srcRate = m.sr;
      else if (m.type === "clear") {
        this.r = this.w;
        this.playing = false;
      }
    };
  }

  write(x) {
    if (this.w - this.r + x.length > this.cap - 2) this.r = this.w - this.cap / 2; // overflow: drop the backlog
    for (let i = 0; i < x.length; i++) this.buf[(this.w + i) % this.cap] = x[i];
    this.w += x.length;
  }

  process(_inputs, outputs) {
    const out = outputs[0][0];
    if (!out) return true;
    const step = this.srcRate / sampleRate;
    const need = this.prebuffer * this.srcRate;
    for (let n = 0; n < out.length; n++) {
      const avail = this.w - this.r;
      if (!this.playing && avail > 1) {
        this.waited++;
        if (avail >= need || this.waited > this.prebuffer * sampleRate) {
          this.playing = true;
          this.waited = 0;
        }
      }
      if (this.playing && avail >= 2) {
        const i = Math.floor(this.r);
        const f = this.r - i;
        const a = this.buf[i % this.cap];
        const b = this.buf[(i + 1) % this.cap];
        this.last = a + (b - a) * f;
        this.r += step;
        this.env = Math.min(1, this.env + this.fadeStep);
      } else {
        if (this.playing) {
          this.playing = false; // underrun: wait for more, fade what we were playing
          this.r = Math.max(this.r, this.w - 1);
        }
        this.env = Math.max(0, this.env - this.fadeStep);
      }
      if (avail <= 1) this.waited = 0;
      out[n] = this.last * this.env;
    }
    for (let c = 1; c < outputs[0].length; c++) outputs[0][c].set(out);
    return true;
  }
}

registerProcessor("pcm-player", PcmPlayer);
