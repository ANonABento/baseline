// Live mic capture -> 16 kHz int16 PCM chunks (~100 ms) via public/pcm-worklet.js.
export interface MicHandle {
  stop: () => void;
}

/** RMS level (0..1) of one int16 PCM chunk; used for the live-mic level meter. */
export function pcmLevel(pcm: ArrayBuffer): number {
  const v = new Int16Array(pcm);
  if (!v.length) return 0;
  let sum = 0;
  for (let i = 0; i < v.length; i++) sum += v[i] * v[i];
  return Math.min(1, Math.sqrt(sum / v.length) / 8000);
}

export function micErrorMessage(e: unknown): string {
  const err = e as { name?: string; message?: string };
  if (!window.isSecureContext) return "Mic needs https or localhost.";
  switch (err?.name) {
    case "NotAllowedError":
      return "Microphone permission denied. Allow it in the browser's site settings.";
    case "NotFoundError":
      return "No microphone found.";
    case "NotReadableError":
      return "Microphone is in use by another app.";
    default:
      return `Mic unavailable: ${err?.message ?? String(e)}`;
  }
}

export async function startMic(onChunk: (pcm: ArrayBuffer) => void, onLevel?: (level: number) => void): Promise<MicHandle> {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("getUserMedia not supported (needs https or localhost)");
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const ctx = new AudioContext();
  const cleanupStream = () => stream.getTracks().forEach((t) => t.stop());
  try {
    // Chrome may create the context suspended if the gesture chain was broken by the await above.
    if (ctx.state === "suspended") await ctx.resume();
    await ctx.audioWorklet.addModule(`${import.meta.env.BASE_URL}pcm-worklet.js`);
  } catch (e) {
    cleanupStream();
    void ctx.close();
    throw e;
  }
  const src = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, "pcm-downsampler");
  node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
    onLevel?.(pcmLevel(e.data));
    onChunk(e.data);
  };
  src.connect(node);
  // Worklets only run when connected to the graph; route to a muted gain so nothing is heard.
  const mute = ctx.createGain();
  mute.gain.value = 0;
  node.connect(mute).connect(ctx.destination);
  let stopped = false;
  return {
    stop: () => {
      if (stopped) return;
      stopped = true;
      node.port.onmessage = null;
      src.disconnect();
      node.disconnect();
      cleanupStream();
      void ctx.close();
      onLevel?.(0);
    },
  };
}
