// THE BASELINE: one thin horizontal line. Flat when calm, spikes where anomalies fire.
// It's the logo, the trust meter and (in the call room) the timeline.
import { useEffect, useRef, useState } from "react";
import type { Tier } from "../lib/notes";
import { useReducedMotion } from "../lib/prefs";

export interface LineSpike {
  id: string;
  /** 0..1 across the line */
  x: number;
  tier: Tier;
  label?: string;
}

interface Props {
  spikes?: LineSpike[];
  /** 0..1 ambient unrest (trust falling) */
  agitation?: number;
  /** spawn transient anomalies on its own (landing page) */
  ambient?: boolean;
  /** gentle travelling pulse (waiting) */
  pulse?: boolean;
  /** 0..1 "now" cursor for the timeline */
  cursor?: number | null;
  activeId?: string | null;
  onSpike?: (id: string) => void;
  /** pointer bends the line a little */
  interactive?: boolean;
  className?: string;
  ariaLabel?: string;
}

const COLORS = {
  line: "#4c4b48",
  noted: "#a3a29d",
  watch: "#e3a33b",
  flag: "#f0353d",
  cursor: "#2c2c2a",
};
const AMP: Record<Tier, number> = { noted: 0.24, watch: 0.5, flag: 0.78 };
const RANK: Record<Tier, number> = { noted: 1, watch: 2, flag: 3 };

interface Live extends LineSpike {
  born: number;
  /** ms; transient spikes fade out */
  life?: number;
}

export function Baseline({ spikes = [], agitation = 0, ambient, pulse, cursor = null, activeId, onSpike, interactive, className, ariaLabel }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const reduced = useReducedMotion();
  const live = useRef(new Map<string, Live>());
  const pointer = useRef<number | null>(null);
  const props = useRef({ agitation, cursor, activeId, pulse });
  props.current = { agitation, cursor, activeId, pulse };
  const [hover, setHover] = useState<{ x: number; label: string; tier: Tier } | null>(null);

  // sync declared spikes (keep birth time so new ones animate in)
  useEffect(() => {
    const now = performance.now();
    const m = live.current;
    const ids = new Set(spikes.map((s) => s.id));
    for (const [id, s] of m) if (!s.life && !ids.has(id)) m.delete(id);
    for (const s of spikes) {
      const old = m.get(s.id);
      m.set(s.id, { ...s, born: old?.born ?? (reduced ? now - 5000 : now) });
    }
  }, [spikes, reduced]);

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    let nextAmbient = performance.now() + 1800;
    let W = 0;
    let H = 0;
    let dpr = 1;
    const resize = () => {
      dpr = Math.min(2, window.devicePixelRatio || 1);
      W = c.clientWidth;
      H = c.clientHeight;
      c.width = Math.round(W * dpr);
      c.height = Math.round(H * dpr);
    };
    const ro = new ResizeObserver(resize);
    ro.observe(c);
    resize();

    const draw = (now: number) => {
      const t = reduced ? 0 : now / 1000;
      const { agitation: ag, cursor: cur, activeId: act, pulse: pl } = props.current;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const mid = Math.round(H / 2) + 0.5;
      const maxA = H * 0.46;

      if (ambient && !reduced && now > nextAmbient) {
        const r = Math.random();
        const tier: Tier = r > 0.86 ? "flag" : r > 0.55 ? "watch" : "noted";
        const id = `amb-${now}`;
        live.current.set(id, { id, x: 0.08 + Math.random() * 0.84, tier, born: now, life: tier === "flag" ? 4200 : 3200 });
        nextAmbient = now + 2200 + Math.random() * 3200;
      }

      const arr = [...live.current.values()];
      const env = (s: Live) => {
        const age = now - s.born;
        const inK = Math.min(1, age / 700);
        let k = 1 - Math.pow(1 - inK, 3);
        if (s.life) {
          const outK = Math.max(0, (age - s.life * 0.55) / (s.life * 0.45));
          k *= 1 - outK;
          if (age > s.life) live.current.delete(s.id);
        }
        return Math.max(0, k);
      };
      const ks = arr.map(env);
      const width = Math.max(7, Math.min(16, W / 90));

      const yAt = (x: number) => {
        let y = 0;
        if (ag > 0) y += (Math.sin(x * 0.09 + t * 3.1) * 0.6 + Math.sin(x * 0.023 - t * 1.7) * 0.4) * ag * maxA * 0.12;
        if (pl) {
          const px = ((t * 0.42) % 1.3 - 0.15) * W;
          const dx = x - px;
          y += Math.exp(-((dx / (W * 0.035)) ** 2)) * Math.sin(dx * 0.12) * maxA * 0.18;
        }
        if (pointer.current != null) {
          const dx = x - pointer.current;
          y += Math.exp(-((dx / 26) ** 2)) * Math.sin(dx * 0.3 + t * 6) * maxA * 0.08;
        }
        for (let i = 0; i < arr.length; i++) {
          const s = arr[i];
          const dx = x - s.x * W;
          if (Math.abs(dx) > width * 3.5) continue;
          const e = Math.exp(-((dx / width) ** 2));
          const wob = 1 + (reduced ? 0 : Math.sin(t * 9 + s.x * 40) * 0.06 * (s.tier === "flag" ? 1 : 0.3));
          y += e * Math.sin(dx * (1.15 / width) * 2.4) * AMP[s.tier] * maxA * ks[i] * wob * (s.id === act ? 1.15 : 1);
        }
        return mid - y;
      };

      // cursor + elapsed span
      if (cur != null) {
        const cx = Math.round(cur * W) + 0.5;
        ctx.strokeStyle = COLORS.cursor;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(cx, 4);
        ctx.lineTo(cx, H - 4);
        ctx.stroke();
      }

      const stroke = (x0: number, x1: number, color: string, lw: number) => {
        ctx.strokeStyle = color;
        ctx.lineWidth = lw;
        ctx.beginPath();
        for (let x = Math.max(0, Math.floor(x0)); x <= Math.min(W, Math.ceil(x1)); x += 1) {
          const y = yAt(x);
          if (x === Math.max(0, Math.floor(x0))) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      };
      const lw = W > 1400 ? 1.5 : 1.25;
      stroke(0, cur != null ? cur * W : W, COLORS.line, lw);
      if (cur != null) {
        ctx.globalAlpha = 0.35;
        stroke(cur * W, W, COLORS.line, 1);
        ctx.globalAlpha = 1;
      }
      // colored overdraw around each spike, lowest tier first
      const order = arr.map((s, i) => ({ s, k: ks[i] })).sort((a, b) => RANK[a.s.tier] - RANK[b.s.tier]);
      for (const { s, k } of order) {
        if (k < 0.02) continue;
        ctx.globalAlpha = Math.min(1, k * 1.4);
        stroke(s.x * W - width * 2.6, s.x * W + width * 2.6, COLORS[s.tier], lw + (s.id === act ? 0.75 : 0.25));
      }
      ctx.globalAlpha = 1;

      const needsFrame = !reduced || ks.some((k) => k < 1) || ambient;
      if (needsFrame && !document.hidden) raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    const wake = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(draw);
    };
    document.addEventListener("visibilitychange", wake);
    const wakeTimer = reduced ? window.setInterval(wake, 1000) : 0;
    return () => {
      cancelAnimationFrame(raf);
      clearInterval(wakeTimer);
      ro.disconnect();
      document.removeEventListener("visibilitychange", wake);
    };
  }, [ambient, reduced]);

  const nearest = (clientX: number): LineSpike | null => {
    const c = canvas.current;
    if (!c || !spikes.length) return null;
    const r = c.getBoundingClientRect();
    const x = (clientX - r.left) / r.width;
    let best: LineSpike | null = null;
    let bd = Infinity;
    for (const s of spikes) {
      const d = Math.abs(s.x - x) * r.width;
      if (d < bd) [best, bd] = [s, d];
    }
    return bd < 18 ? best : null;
  };

  return (
    <div className={`baseline ${className ?? ""}`}>
      <canvas
        ref={canvas}
        role={onSpike ? "presentation" : "img"}
        aria-label={ariaLabel ?? "Baseline"}
        style={{ cursor: hover && onSpike ? "pointer" : undefined }}
        onPointerMove={(e) => {
          if (interactive) pointer.current = e.clientX - e.currentTarget.getBoundingClientRect().left;
          if (onSpike) {
            const s = nearest(e.clientX);
            setHover(s ? { x: s.x, label: s.label ?? "", tier: s.tier } : null);
          }
        }}
        onPointerLeave={() => {
          pointer.current = null;
          setHover(null);
        }}
        onClick={(e) => {
          const s = nearest(e.clientX);
          if (s && onSpike) onSpike(s.id);
        }}
      />
      {hover?.label && (
        <div className={`baseline-tip tier-${hover.tier}`} style={{ left: `${hover.x * 100}%` }}>
          {hover.label}
        </div>
      )}
      {onSpike && spikes.length > 0 && (
        <div className="sr-only">
          {spikes.map((s) => (
            <button key={s.id} onClick={() => onSpike(s.id)}>
              {s.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
