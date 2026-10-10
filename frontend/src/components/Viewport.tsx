import { useEffect, useRef, useState } from "react";
import { Stage, webglAvailable, type SourceKind } from "../gl/stage";
import { useReducedMotion, useRenderStyle } from "../lib/prefs";

interface Props {
  source: SourceKind;
  video?: HTMLVideoElement | null;
  /** per-frame loudness source */
  level?: () => number;
  chaos?: number;
  resolve?: number;
  scale?: number;
  drift?: boolean;
  zoom?: number;
  className?: string;
  label?: string;
}

const FALLBACK_ROWS = 14;

// ?chaos=0..1 / ?resolve=0..1 force a state on every viewport (for tuning the look)
const params = new URLSearchParams(location.search);
const FORCE_CHAOS = params.has("chaos") ? Number(params.get("chaos")) : null;
const FORCE_RESOLVE = params.has("resolve") ? Number(params.get("resolve")) : null;

/** Static glyph field when WebGL isn't available. */
function GlyphFallback({ chaos = 0 }: { chaos?: number }) {
  const ramp = " .:-=+*#";
  const rows = Array.from({ length: FALLBACK_ROWS }, (_, y) =>
    Array.from({ length: 36 }, (_, x) => {
      const d = Math.hypot((x - 18) / 18, (y - 7) / 7);
      const v = Math.max(0, 1 - d) * (0.6 + 0.4 * Math.sin(x * 1.7 + y * 2.3));
      const jitter = chaos > 0.3 && (x * 7 + y * 13) % 5 === 0 ? 0.5 : 0;
      return ramp[Math.min(ramp.length - 1, Math.floor((v + jitter) * ramp.length))];
    }).join(""),
  );
  return (
    <pre className="glyph-fallback" aria-hidden>
      {rows.join("\n")}
    </pre>
  );
}

export function Viewport({ source, video = null, level, chaos = 0, resolve = 0, scale, drift, zoom, className, label }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const stage = useRef<Stage | null>(null);
  const style = useRenderStyle();
  const reduced = useReducedMotion();
  const [gl] = useState(webglAvailable);
  const levelRef = useRef(level);
  levelRef.current = level;

  useEffect(() => {
    if (!gl || !canvas.current) return;
    let s: Stage | null = null;
    try {
      s = new Stage({ canvas: canvas.current, source, style, video, scale, drift, zoom, reducedMotion: reduced });
    } catch {
      return;
    }
    s.levelFn = () => levelRef.current?.() ?? 0;
    stage.current = s;
    return () => {
      s?.dispose();
      stage.current = null;
    };
    // the stage is rebuilt only when its identity-defining options change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gl, source, scale, reduced]);

  useEffect(() => stage.current?.setStyle(style), [style]);
  useEffect(() => stage.current?.setVideo(video), [video]);
  useEffect(() => {
    if (!stage.current) return;
    stage.current.target.chaos = FORCE_CHAOS ?? chaos;
    stage.current.target.resolve = FORCE_RESOLVE ?? resolve;
  }, [chaos, resolve]);

  return (
    <div className={`viewport ${className ?? ""}`} role={label ? "img" : undefined} aria-label={label}>
      {gl ? <canvas ref={canvas} /> : <GlyphFallback chaos={chaos} />}
    </div>
  );
}
