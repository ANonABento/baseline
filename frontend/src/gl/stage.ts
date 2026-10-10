// One WebGL canvas that draws a source (3D head, webcam, or an abstract field) in one of
// two styles: ASCII glyph shader or 1-bit ordered dither. Controls are
// plain mutable numbers (targets) that the frame loop eases toward, so React never
// re-renders per frame.
import * as THREE from "three";
import { loadHead } from "./head";
import { personMask, type PersonMask } from "../lib/segment";
import {
  ASCII_FRAG,
  DITHER_FRAG,
  HEAD_FRAG,
  HEAD_VERT,
  QUAD_VERT,
  SOURCE_FRAG,
} from "./shaders";

export type RenderStyle = "ascii" | "dither";
export type SourceKind = "head" | "video";

export interface Controls {
  /** speaking loudness 0..1 */
  level: number;
  /** destabilize 0..1 (alert) */
  chaos: number;
  /** settle 0..1 (calm / verified) */
  resolve: number;
}

export interface StageOptions {
  canvas: HTMLCanvasElement;
  source: SourceKind;
  style: RenderStyle;
  video?: HTMLVideoElement | null;
  /** ASCII cell height / dither pixel / point spacing, in CSS px */
  scale?: number;
  /** slow camera drift for the head */
  drift?: boolean;
  /** head framing: >1 moves the camera closer */
  zoom?: number;
  reducedMotion?: boolean;
}

const INK = new THREE.Color("#ecebe6");
const DIM = new THREE.Color("#5e5d59");
const RED = new THREE.Color("#f0353d");
const GLYPHS = " .:-=+*#%@";

export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!c.getContext("webgl2");
  } catch {
    return false;
  }
}

function glyphAtlas(): THREE.CanvasTexture {
  // cells match the on-screen character cell (0.62 : 1) so glyphs aren't squashed
  const size = 64;
  const cw = Math.round(size * 0.62);
  const c = document.createElement("canvas");
  c.width = cw * GLYPHS.length;
  c.height = size;
  const ctx = c.getContext("2d")!;
  const draw = () => {
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.fillStyle = "#fff";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = `500 ${size * 0.86}px "Geist Mono", ui-monospace, Menlo, monospace`;
    for (let i = 0; i < GLYPHS.length; i++) ctx.fillText(GLYPHS[i], i * cw + cw / 2, size * 0.54);
  };
  draw();
  const tex = new THREE.CanvasTexture(c);
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.generateMipmaps = false;
  document.fonts?.ready.then(() => {
    draw();
    tex.needsUpdate = true;
  });
  return tex;
}

let atlas: THREE.CanvasTexture | null = null;

export class Stage {
  readonly target: Controls = { level: 0, chaos: 0, resolve: 0 };
  /** optional per-frame level source (e.g. live audio RMS held in a ref) */
  levelFn: (() => number) | null = null;
  private cur: Controls = { level: 0, chaos: 0, resolve: 0 };
  private renderer: THREE.WebGLRenderer;
  private opts: StageOptions;
  private style: RenderStyle;
  private last = performance.now();
  private elapsed = 0;
  private raf = 0;
  private idle = 0;
  private visible = true;
  private disposed = false;
  private w = 1;
  private h = 1;
  private dpr = 1;
  private ro: ResizeObserver;
  private io: IntersectionObserver;
  // source (rendered to a target for ascii/dither)
  private rt: THREE.WebGLRenderTarget;
  private srcScene = new THREE.Scene();
  private headCam = new THREE.PerspectiveCamera(26, 1, 0.1, 50);
  private quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  private headGroup = new THREE.Group();
  private headMat: THREE.ShaderMaterial | null = null;
  private srcMat: THREE.ShaderMaterial | null = null;
  private videoTex: THREE.VideoTexture | null = null;
  /** person segmentation for the webcam: the background drops out */
  private mask: PersonMask | null = null;
  // post
  private postScene = new THREE.Scene();
  private postMat: THREE.ShaderMaterial | null = null;
  private headGeo: THREE.BufferGeometry | null = null;
  private onVis = () => this.loop();

  constructor(opts: StageOptions) {
    this.opts = opts;
    this.style = opts.style;
    this.renderer = new THREE.WebGLRenderer({ canvas: opts.canvas, antialias: false, alpha: false, powerPreference: "low-power" });
    this.renderer.setClearColor(0x000000, 1);
    this.renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
    this.rt = new THREE.WebGLRenderTarget(4, 4, { depthBuffer: true });
    this.headCam.position.set(0, 0.12, 4.9);
    this.srcScene.add(this.headGroup);
    this.setVideo(opts.video ?? null);
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(opts.canvas);
    this.io = new IntersectionObserver((es) => {
      this.visible = es.some((e) => e.isIntersecting);
      this.loop();
    });
    this.io.observe(opts.canvas);
    document.addEventListener("visibilitychange", this.onVis);
    this.resize();
    this.build();
    if (opts.source === "head") {
      void loadHead().then((g) => {
        if (this.disposed) return;
        this.headGeo = g;
        this.build();
      });
    }
    this.loop();
  }

  setStyle(s: RenderStyle) {
    if (s === this.style) return;
    this.style = s;
    this.build();
  }

  setVideo(v: HTMLVideoElement | null) {
    this.opts.video = v;
    this.mask?.release();
    this.mask = v ? personMask(v) : null;
    this.mask?.retain();
    this.videoTex?.dispose();
    this.videoTex = v ? new THREE.VideoTexture(v) : null;
    if (this.videoTex) this.videoTex.colorSpace = THREE.NoColorSpace;
    const u = this.srcMat?.uniforms;
    if (u) {
      u.uTex.value = this.videoTex;
      u.uHasTex.value = this.videoTex ? 1 : 0;
      u.uMask.value = this.mask?.texture ?? null;
    }
  }

  private cssScale(): number {
    return this.opts.scale ?? (this.style === "ascii" ? 11 : 2);
  }

  private clear(scene: THREE.Scene, keep: THREE.Object3D[] = []) {
    for (const o of [...scene.children]) {
      if (keep.includes(o)) continue;
      scene.remove(o);
      const m = o as THREE.Mesh;
      if (m.geometry && m.geometry !== this.headGeo) m.geometry.dispose();
      const mat = m.material as THREE.Material | undefined;
      mat?.dispose?.();
    }
  }

  /** (Re)build the scenes for the current style and source. */
  private build() {
    this.clear(this.postScene);
    for (const o of [...this.headGroup.children]) {
      this.headGroup.remove(o);
      const m = o as THREE.Mesh;
      (m.material as THREE.Material).dispose();
      if (m.geometry !== this.headGeo) m.geometry.dispose();
    }
    this.clear(this.srcScene, [this.headGroup]);
    this.headMat = this.srcMat = this.postMat = null;
    const common = () => ({
      uTime: { value: 0 },
      uChaos: { value: 0 },
      uLevel: { value: 0 },
      uResolve: { value: 0 },
    });
    const quad = new THREE.PlaneGeometry(2, 2);
    const colors = { uInk: { value: INK }, uDim: { value: DIM }, uRed: { value: RED } };

    // source pass into the render target, then a post quad (glyphs or dither)
    if (this.opts.source === "head") {
      if (this.headGeo) {
        this.headMat = new THREE.ShaderMaterial({ vertexShader: HEAD_VERT, fragmentShader: HEAD_FRAG, uniforms: common() });
        this.headGroup.add(new THREE.Mesh(this.headGeo, this.headMat));
      }
      this.srcScene.add(this.headGroup);
    } else {
      this.srcMat = new THREE.ShaderMaterial({
        vertexShader: QUAD_VERT,
        fragmentShader: SOURCE_FRAG,
        uniforms: {
          ...common(),
          uTex: { value: this.videoTex },
          uHasTex: { value: this.videoTex ? 1 : 0 },
          uMask: { value: this.mask?.texture ?? null },
          uHasMask: { value: 0 },
          uCover: { value: new THREE.Vector4(1, 1, 0, 0) },
        },
        depthTest: false,
      });
      this.srcScene.add(new THREE.Mesh(quad.clone(), this.srcMat));
    }
    if (this.style === "ascii") {
      atlas ??= glyphAtlas();
      this.postMat = new THREE.ShaderMaterial({
        vertexShader: QUAD_VERT,
        fragmentShader: ASCII_FRAG,
        uniforms: {
          ...common(),
          ...colors,
          uSrc: { value: this.rt.texture },
          uAtlas: { value: atlas },
          uRes: { value: new THREE.Vector2(1, 1) },
          uCell: { value: 12 },
          uGlyphs: { value: GLYPHS.length },
        },
        depthTest: false,
      });
    } else {
      this.postMat = new THREE.ShaderMaterial({
        vertexShader: QUAD_VERT,
        fragmentShader: DITHER_FRAG,
        uniforms: { ...common(), ...colors, uSrc: { value: this.rt.texture }, uRes: { value: new THREE.Vector2(1, 1) }, uPx: { value: 2 } },
        depthTest: false,
      });
    }
    this.postScene.add(new THREE.Mesh(quad, this.postMat));
    this.resize();
  }

  private resize() {
    const c = this.opts.canvas;
    const w = Math.max(1, c.clientWidth);
    const h = Math.max(1, c.clientHeight);
    this.dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    this.w = w;
    this.h = h;
    this.renderer.setPixelRatio(this.dpr);
    this.renderer.setSize(w, h, false);
    const pw = Math.round(w * this.dpr);
    const ph = Math.round(h * this.dpr);
    this.rt.setSize(pw, ph);
    this.headCam.aspect = w / h;
    // fit ~2.5 units of height (and ~1.9 of width) whatever the tile's aspect
    const tanHalf = Math.tan(THREE.MathUtils.degToRad(this.headCam.fov / 2));
    this.headCam.position.z = Math.max(1.25 / tanHalf, 0.95 / (tanHalf * (w / h))) / (this.opts.zoom ?? 1);
    this.headCam.updateProjectionMatrix();
    const s = this.cssScale() * this.dpr;
    const u = this.postMat?.uniforms;
    if (u) {
      u.uRes.value.set(pw, ph);
      if (u.uCell) u.uCell.value = s;
      if (u.uPx) u.uPx.value = Math.max(1, Math.round(s));
    }
    this.renderOnce();
  }

  private cover(): THREE.Vector4 {
    const v = this.opts.video;
    if (!v || !v.videoWidth) return new THREE.Vector4(1, 1, 0, 0);
    const va = v.videoWidth / v.videoHeight;
    const ca = this.w / this.h;
    if (va > ca) {
      const sx = ca / va;
      return new THREE.Vector4(sx, 1, (1 - sx) / 2, 0);
    }
    const sy = va / ca;
    return new THREE.Vector4(1, sy, 0, (1 - sy) / 2);
  }

  private loop() {
    cancelAnimationFrame(this.raf);
    clearTimeout(this.idle);
    if (this.disposed || document.hidden || !this.visible) return;
    const tick = () => {
      this.renderOnce();
      if (!this.opts.reducedMotion || this.cur.chaos > 0.01 || this.target.chaos > 0.01) this.raf = requestAnimationFrame(tick);
      else this.idle = window.setTimeout(() => (this.raf = requestAnimationFrame(tick)), 250);
    };
    this.raf = requestAnimationFrame(tick);
  }

  private renderOnce() {
    if (this.disposed) return;
    const nowMs = performance.now();
    const dt = Math.min(0.1, (nowMs - this.last) / 1000);
    this.last = nowMs;
    this.elapsed += dt;
    if (this.levelFn) this.target.level = this.levelFn();
    const t = this.elapsed * (this.opts.reducedMotion ? 0.25 : 1);
    const ease = (k: keyof Controls, rate: number) => {
      this.cur[k] += (this.target[k] - this.cur[k]) * Math.min(1, dt * rate);
    };
    ease("level", 14);
    ease("chaos", 2.2);
    ease("resolve", 1.5);
    const set = (m: THREE.ShaderMaterial | null) => {
      if (!m) return;
      const u = m.uniforms;
      u.uTime.value = t;
      u.uChaos.value = this.cur.chaos;
      u.uLevel.value = this.cur.level;
      u.uResolve.value = this.cur.resolve;
      if (u.uCover) u.uCover.value = this.cover();
      if (u.uHasMask) u.uHasMask.value += ((this.mask?.ready ? 1 : 0) - u.uHasMask.value) * Math.min(1, dt * 4);
    };
    [this.headMat, this.srcMat, this.postMat].forEach(set);

    if (this.opts.source === "head") {
      // facing the viewer and breathing (~4.5 s cycle: slow in, quicker out), with only
      // a faint sway so it reads as alive rather than as a turntable
      const drift = this.opts.drift !== false && !this.opts.reducedMotion;
      const ph = t * 1.4;
      const breath = Math.pow(0.5 - 0.5 * Math.cos(ph), 1.6);
      this.headGroup.scale.set(1 + breath * 0.022, 1 + breath * 0.03, 1 + breath * 0.022);
      this.headGroup.position.y = breath * 0.035 - 0.015;
      this.headGroup.rotation.x = 0.05 - breath * 0.035;
      this.headGroup.rotation.y = drift ? Math.sin(t * 0.09) * 0.05 : 0;
    }

    this.renderer.setRenderTarget(this.rt);
    this.renderer.render(this.srcScene, this.opts.source === "head" ? this.headCam : this.quadCam);
    this.renderer.setRenderTarget(null);
    this.renderer.render(this.postScene, this.quadCam);
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    clearTimeout(this.idle);
    this.ro.disconnect();
    this.io.disconnect();
    document.removeEventListener("visibilitychange", this.onVis);
    this.clear(this.postScene);
    this.clear(this.srcScene);
    this.videoTex?.dispose();
    this.mask?.release();
    this.rt.dispose();
    this.renderer.dispose();
  }
}
