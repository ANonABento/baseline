import type { ReactNode } from "react";
import { linkTo, RENDER_STYLES, setRenderStyle, STYLE_LABEL, useRenderStyle } from "../lib/prefs";

export function Mark({ alert = false }: { alert?: boolean }) {
  return (
    <svg width="30" height="14" viewBox="0 0 30 14" aria-hidden>
      <path d="M0 7.5 H13 L15 2.5 L17 12 L18.5 7.5 H30" fill="none" stroke={alert ? "var(--red)" : "currentColor"} strokeWidth="1.25" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <a className="wordmark" href="/" onClick={linkTo("/")}>
      <Mark />
      Baseline
    </a>
  );
}

export function RenderToggle() {
  const style = useRenderStyle();
  return (
    <div className="render-toggle" role="group" aria-label="Render style">
      {RENDER_STYLES.map((s) => (
        <button key={s} type="button" aria-pressed={style === s} onClick={() => setRenderStyle(s)}>
          {STYLE_LABEL[s]}
        </button>
      ))}
    </div>
  );
}

export function TopBar({ children, rule = false }: { children?: ReactNode; rule?: boolean }) {
  return (
    <header className={`topbar ${rule ? "topbar--rule" : ""}`}>
      <Wordmark />
      <div className="topbar__spacer" />
      {children}
      <RenderToggle />
    </header>
  );
}
