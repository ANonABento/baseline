import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cx } from "./Panel";

/**
 * Hover/focus tooltip rendered in a portal with fixed positioning, so it is never clipped
 * by scrolling panels. Wraps its children in an inline-flex span.
 */
export function Tip({ content, children, className, style, as = "span", tabIndex }: {
  content: ReactNode; children: ReactNode; className?: string; style?: CSSProperties; as?: "span" | "div"; tabIndex?: number;
}) {
  const ref = useRef<HTMLElement | null>(null);
  const bubble = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    if (!open || !ref.current || !bubble.current) return;
    const r = ref.current.getBoundingClientRect();
    const b = bubble.current.getBoundingClientRect();
    const pad = 8;
    let left = Math.min(Math.max(pad, r.left + r.width / 2 - b.width / 2), window.innerWidth - b.width - pad);
    let top = r.top - b.height - 8;
    if (top < pad) top = r.bottom + 8;
    left = Math.round(left);
    top = Math.round(top);
    setPos((p) => (p && p.left === left && p.top === top ? p : { left, top }));
  }, [open, content]);

  const Tag = as;
  const show = () => setOpen(true);
  const hide = () => { setOpen(false); setPos(null); };
  return (
    <Tag
      ref={(el: HTMLElement | null) => { ref.current = el; }}
      className={className}
      style={style}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      tabIndex={tabIndex}
    >
      {children}
      {open && content && createPortal(
        <div
          ref={bubble}
          role="tooltip"
          className={cx(
            "pointer-events-none fixed z-[100] max-w-sm rounded-lg border border-slate-700 bg-slate-900/95 px-3 py-2 text-sm leading-snug text-slate-100 shadow-xl shadow-black/40 backdrop-blur",
            pos ? "opacity-100" : "opacity-0",
          )}
          style={{ left: pos?.left ?? 0, top: pos?.top ?? 0 }}
        >
          {content}
        </div>,
        document.body,
      )}
    </Tag>
  );
}
