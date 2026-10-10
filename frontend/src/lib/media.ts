// Camera stream shared between the lobby and the call room, so the visitor is asked once.
// The camera never leaves the device: frames only feed the local WebGL renderer.

let stream: MediaStream | null = null;
let video: HTMLVideoElement | null = null;
/** mic picked in the lobby, reused by the call room */
export const micChoice = { deviceId: "" };

export async function startCamera(deviceId?: string): Promise<HTMLVideoElement> {
  stopCamera();
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera needs https or localhost.");
  stream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user", ...(deviceId ? { deviceId: { exact: deviceId } } : {}) },
    audio: false,
  });
  const v = document.createElement("video");
  v.muted = true;
  v.playsInline = true;
  v.srcObject = stream;
  await v.play().catch(() => undefined);
  video = v;
  return v;
}

export function currentCamera(): HTMLVideoElement | null {
  return video && stream?.active ? video : null;
}

export function stopCamera() {
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
  video = null;
}

export function cameraError(e: unknown): string {
  const err = e as { name?: string; message?: string };
  if (!window.isSecureContext) return "Camera needs https or localhost.";
  switch (err?.name) {
    case "NotAllowedError":
      return "Camera blocked. You can join without it.";
    case "NotFoundError":
      return "No camera found. You can join without it.";
    case "NotReadableError":
      return "Camera is in use by another app.";
    default:
      return "Camera unavailable. You can join without it.";
  }
}

/** Mic level meter for the lobby (AnalyserNode, nothing is sent anywhere). */
export async function micMeter(onLevel: (v: number) => void, deviceId?: string): Promise<() => void> {
  micChoice.deviceId = deviceId ?? "";
  const s = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, ...(deviceId ? { deviceId: { exact: deviceId } } : {}) },
  });
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(s);
  const an = ctx.createAnalyser();
  an.fftSize = 1024;
  src.connect(an);
  const buf = new Float32Array(an.fftSize);
  let raf = 0;
  const tick = () => {
    an.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    onLevel(Math.min(1, Math.sqrt(sum / buf.length) * 6));
    raf = requestAnimationFrame(tick);
  };
  tick();
  return () => {
    cancelAnimationFrame(raf);
    s.getTracks().forEach((t) => t.stop());
    void ctx.close();
    onLevel(0);
  };
}
