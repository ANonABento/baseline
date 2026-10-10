// Small stroke icons (24px grid, currentColor). Paired with text labels so color is never
// the only signal.
import type { SignalName } from "../types";
import type { Tone } from "../analysis";

type P = { className?: string; title?: string };
const base = (className = "h-4 w-4") => ({
  className, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true,
});

export const IconUser = ({ className }: P) => (
  <svg {...base(className)}><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></svg>
);
export const IconWave = ({ className }: P) => (
  <svg {...base(className)}><path d="M3 12h2M7 8v8M11 4v16M15 8v8M19 11v2M21 12h0" /></svg>
);
export const IconScript = ({ className }: P) => (
  <svg {...base(className)}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6M8 13h8M8 17h5" /></svg>
);
export const IconGauge = ({ className }: P) => (
  <svg {...base(className)}><path d="M4 18a8 8 0 1 1 16 0" /><path d="M12 18l4-6" /></svg>
);
export const IconShield = ({ className }: P) => (
  <svg {...base(className)}><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M9 12l2 2 4-4" /></svg>
);
export const IconAlert = ({ className }: P) => (
  <svg {...base(className)}><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></svg>
);
export const IconInfo = ({ className }: P) => (
  <svg {...base(className)}><circle cx="12" cy="12" r="9" /><path d="M12 16v-4M12 8h.01" /></svg>
);
export const IconCheck = ({ className }: P) => (
  <svg {...base(className)}><circle cx="12" cy="12" r="9" /><path d="M8 12l3 3 5-6" /></svg>
);
export const IconX = ({ className }: P) => (
  <svg {...base(className)}><path d="M18 6L6 18M6 6l12 12" /></svg>
);
export const IconLink = ({ className }: P) => (
  <svg {...base(className)}><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></svg>
);
export const IconPlay = ({ className }: P) => (
  <svg {...base(className)}><path d="M7 4l13 8-13 8z" fill="currentColor" /></svg>
);
export const IconStop = ({ className }: P) => (
  <svg {...base(className)}><rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor" /></svg>
);
export const IconMic = ({ className }: P) => (
  <svg {...base(className)}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
);
export const IconArrowRight = ({ className }: P) => (
  <svg {...base(className)}><path d="M5 12h14M13 6l6 6-6 6" /></svg>
);
export const IconQuote = ({ className }: P) => (
  <svg {...base(className)}><path d="M7 7h4v4c0 3-2 5-4 6M15 7h4v4c0 3-2 5-4 6" /></svg>
);

export function SignalIcon({ signal, className }: { signal: SignalName; className?: string }) {
  switch (signal) {
    case "speaker": return <IconUser className={className} />;
    case "spoof": return <IconWave className={className} />;
    case "fraud": return <IconScript className={className} />;
    case "prosody": return <IconGauge className={className} />;
  }
}

export function ToneIcon({ tone, className }: { tone: Tone; className?: string }) {
  if (tone === "flag") return <IconAlert className={className} />;
  if (tone === "watch") return <IconInfo className={className} />;
  return <IconCheck className={className} />;
}

/** Logo mark: a flat line (the baseline) with a single deviation. */
export function LogoMark({ className = "h-7 w-7" }: P) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="rgb(79 70 229)" />
      <path d="M5 19h7l2.5-8 3.5 12 2.5-4H27" fill="none" stroke="white" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
