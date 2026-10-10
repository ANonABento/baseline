import type { ReactNode } from "react";
import { linkTo } from "../lib/prefs";

export function Mark({ alert = false }: { alert?: boolean }) {
  return (
    // the logo: the baseline rising into a person (public/brand/logo.jpg)
    <svg width="32" height="16" viewBox="0 0 32 16" aria-hidden>
      <path d="M0 13 H2.5 L3.3 12.5 L4 13.3 L4.8 12.2 L5.5 13.2 L6.3 12.7 L7 13.1 L8.6 13 L9.2 10 Q9.6 8.3 12.2 7.8 Q14 7.4 14.3 6.3 Q13.2 5.4 13.2 3.4 Q13.2 0.6 16 0.6 Q18.8 0.6 18.8 3.4 Q18.8 5.4 17.7 6.3 Q18 7.4 19.8 7.8 Q22.4 8.3 22.8 10 L23.4 13 H32" fill="none" stroke={alert ? "var(--red)" : "currentColor"} strokeWidth="1.1" strokeLinejoin="round" />
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
