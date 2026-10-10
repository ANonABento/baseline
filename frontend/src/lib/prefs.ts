// Small shared UI state: render style per source, reduced motion, routing.
import { useEffect, useState, useSyncExternalStore } from "react";
import type { RenderStyle, SourceKind } from "../gl/stage";

/** The caller (AI head) is always glyphs, half-seen; people on camera are always dither. */
export function renderStyleFor(source: SourceKind): RenderStyle {
  return source === "head" ? "ascii" : "dither";
}

export function useReducedMotion(): boolean {
  const q = "(prefers-reduced-motion: reduce)";
  const [v, setV] = useState(() => window.matchMedia?.(q).matches ?? false);
  useEffect(() => {
    const m = window.matchMedia?.(q);
    if (!m) return;
    const on = () => setV(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return v;
}

// ---------------------------------------------------------------- router (history API)

const routeListeners = new Set<() => void>();
window.addEventListener("popstate", () => routeListeners.forEach((l) => l()));

export function navigate(to: string, replace = false) {
  // keep debugging params (?mock=1, ?tts=...) across navigation
  const keep = new URLSearchParams(location.search);
  const url = new URL(to, location.origin);
  for (const k of ["mock", "tts"]) if (keep.has(k) && !url.searchParams.has(k)) url.searchParams.set(k, keep.get(k)!);
  const href = url.pathname + url.search + url.hash;
  if (replace) history.replaceState(null, "", href);
  else history.pushState(null, "", href);
  routeListeners.forEach((l) => l());
  if (!url.hash) window.scrollTo(0, 0);
}

export function usePath(): string {
  return useSyncExternalStore(
    (cb) => {
      routeListeners.add(cb);
      return () => routeListeners.delete(cb);
    },
    () => location.pathname,
  );
}

/** <a> click handler for in-app links (keeps cmd-click working). */
export function linkTo(to: string) {
  return (e: React.MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    navigate(to);
  };
}
