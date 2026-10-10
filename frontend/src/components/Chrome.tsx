import type { ReactNode } from "react";
import { linkTo } from "../lib/prefs";

export function Mark({ alert = false }: { alert?: boolean }) {
  const c = alert ? "var(--red)" : "currentColor";
  return (
    // the logo: a heartbeat baseline that rises into a person, inside a ring (public/brand/logo.svg)
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
      <mask id="mark-gap">
        <rect width="32" height="32" fill="#fff" />
        <rect x="0" y="17.9" width="5.4" height="3" fill="#000" />
        <rect x="26.6" y="17.9" width="5.4" height="3" fill="#000" />
      </mask>
      <circle cx="16" cy="16" r="12.3" fill="none" stroke={c} strokeWidth="1" mask="url(#mark-gap)" />
      <path d="M3.6 19.4 H6.9 L7.7 17.7 L8.4 20.9 L9.5 15.2 L10.6 23 L11.6 18.3 L12.1 18.9 H12.8 L13.4 17 Q13.8 15.4 16 14.9 Q16.8 14.6 16.3 14 Q15.3 12.9 15.3 11.3 Q15.3 9.1 17.35 9.1 Q19.4 9.1 19.4 11.3 Q19.4 12.9 18.4 14 Q17.9 14.6 18.7 14.9 Q21.3 15.6 21.8 17 L22.3 19.4 H28.4" fill="none" stroke={c} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
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

export function TopBar({ children, rule = false }: { children?: ReactNode; rule?: boolean }) {
  return (
    <header className={`topbar ${rule ? "topbar--rule" : ""}`}>
      <Wordmark />
      <div className="topbar__spacer" />
      {children}
    </header>
  );
}
