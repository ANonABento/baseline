// Live mic capture -> 16 kHz int16 PCM chunks (via public/pcm-worklet.js).
export interface MicHandle {
  stop: () => void;
}

export async function startMic(onChunk: (pcm: ArrayBuffer) => void): Promise<MicHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const ctx = new AudioContext();
  await ctx.audioWorklet.addModule("/pcm-worklet.js");
  const src = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, "pcm-downsampler");
  node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => onChunk(e.data);
  src.connect(node);
  // Worklets only run when connected to the graph; route to a muted gain so nothing is heard.
  const mute = ctx.createGain();
  mute.gain.value = 0;
  node.connect(mute).connect(ctx.destination);
  return {
    stop: () => {
      node.port.onmessage = null;
      src.disconnect();
      node.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close();
    },
  };
}
