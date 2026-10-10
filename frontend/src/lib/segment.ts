// Person mask for the webcam, the same approach Google Meet uses for background blur: MediaPipe's
// selfie segmenter, on-device. The wasm runtime and model are served from /public so it works
// offline; frames never leave the browser. One mask per video element, shared by every viewport
// that draws it. If the model can't load, the mask stays empty and the renderers ignore it.
import * as THREE from "three";
import type { ImageSegmenter } from "@mediapipe/tasks-vision";

// mask resolution: small on purpose (cheap to upload; linear filtering softens the edge)
const MW = 160;
const MH = 120;
/** seconds between segmentations (~20 fps is plenty for a stylized render) */
const STEP = 1 / 20;

let segmenter: Promise<ImageSegmenter | null> | null = null;

function loadSegmenter(): Promise<ImageSegmenter | null> {
  segmenter ??= (async () => {
    try {
      const { ImageSegmenter } = await import("@mediapipe/tasks-vision");
      const base = `${import.meta.env.BASE_URL}mediapipe/`;
      const fileset = {
        wasmLoaderPath: `${base}vision_wasm_internal.js`,
        wasmBinaryPath: `${base}vision_wasm_internal.wasm`,
      };
      const make = (delegate: "GPU" | "CPU") =>
        ImageSegmenter.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: `${import.meta.env.BASE_URL}models/selfie_segmenter.tflite`, delegate },
          runningMode: "VIDEO",
          outputCategoryMask: false,
          outputConfidenceMasks: true,
        });
      return await make("GPU").catch(() => make("CPU"));
    } catch (e) {
      console.warn("person segmentation unavailable", e);
      return null;
    }
  })();
  return segmenter;
}

export class PersonMask {
  readonly texture: THREE.DataTexture;
  /** true once the first mask has landed */
  ready = false;
  private data = new Uint8Array(MW * MH);
  private acc = new Float32Array(MW * MH);
  private video: HTMLVideoElement;
  private seg: ImageSegmenter | null = null;
  private raf = 0;
  private last = -1;
  private lastTs = 0;
  private refs = 0;

  constructor(video: HTMLVideoElement) {
    this.video = video;
    this.texture = new THREE.DataTexture(this.data, MW, MH, THREE.RedFormat, THREE.UnsignedByteType);
    this.texture.minFilter = THREE.LinearFilter;
    this.texture.magFilter = THREE.LinearFilter;
    this.texture.needsUpdate = true;
    void loadSegmenter().then((s) => {
      this.seg = s;
      if (s && this.refs > 0) this.loop();
    });
  }

  private loop() {
    cancelAnimationFrame(this.raf);
    const tick = (now: number) => {
      this.raf = requestAnimationFrame(tick);
      if (document.hidden || this.video.readyState < 2 || !this.video.videoWidth) return;
      if (now - this.last < STEP * 1000) return;
      this.last = now;
      this.run(now);
    };
    this.raf = requestAnimationFrame(tick);
  }

  private run(now: number) {
    const seg = this.seg;
    if (!seg) return;
    // timestamps must strictly increase
    const ts = Math.max(now, this.lastTs + 1);
    this.lastTs = ts;
    let res;
    try {
      res = seg.segmentForVideo(this.video, ts);
    } catch {
      return;
    }
    const mask = res.confidenceMasks?.[0];
    if (!mask) return res.close?.();
    const src = mask.getAsFloat32Array();
    const w = mask.width;
    const h = mask.height;
    // downsample (nearest) + flip rows into GL order, with a little temporal smoothing so the
    // edge doesn't crawl; the first mask lands at full weight
    const k = this.ready ? 0.55 : 1;
    for (let y = 0; y < MH; y++) {
      const sy = Math.min(h - 1, Math.floor(((MH - 1 - y) + 0.5) * (h / MH)));
      for (let x = 0; x < MW; x++) {
        const sx = Math.min(w - 1, Math.floor((x + 0.5) * (w / MW)));
        const i = y * MW + x;
        this.acc[i] += (src[sy * w + sx] - this.acc[i]) * k;
        this.data[i] = Math.round(this.acc[i] * 255);
      }
    }
    res.close();
    this.texture.needsUpdate = true;
    this.ready = true;
  }

  retain() {
    this.refs++;
    if (this.refs === 1 && this.seg) this.loop();
  }

  release() {
    this.refs = Math.max(0, this.refs - 1);
    if (this.refs === 0) cancelAnimationFrame(this.raf);
  }
}

const masks = new WeakMap<HTMLVideoElement, PersonMask>();

/** The shared person mask for a video element (caller must retain/release). */
export function personMask(video: HTMLVideoElement): PersonMask {
  let m = masks.get(video);
  if (!m) {
    m = new PersonMask(video);
    masks.set(video, m);
  }
  return m;
}
