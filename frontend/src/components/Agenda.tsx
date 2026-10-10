import { useEffect, useState } from "react";
import type { Agenda } from "../lib/contract";

/** Scammer side: the visitor's cheat sheet for this call (target, goal, beats, lines, comebacks). C toggles it. */
export function AgendaPanel({ agenda }: { agenda: Agenda }) {
  const [open, setOpen] = useState(true);
  const [done, setDone] = useState<Set<number>>(new Set());

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable) return;
      if (e.key === "c" || e.key === "C") setOpen((o) => !o);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const toggle = (i: number) =>
    setDone((d) => {
      const n = new Set(d);
      if (n.has(i)) n.delete(i);
      else n.add(i);
      return n;
    });

  return (
    <section className={`agenda ${open ? "" : "agenda--closed"}`} aria-label="Your agenda">
      <button type="button" className="agenda__head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="label">Your agenda</span>
        <span className="agenda__target">
          Calling <b>{agenda.target.name}</b>
        </span>
        <span className="label agenda__key">{open ? "Hide" : "Show"} · C</span>
      </button>
      {open && (
        <div className="agenda__body">
          <p className="agenda__profile">{agenda.target.profile}</p>
          <div className="agenda__row">
            <span className="label">Goal</span>
            <p>{agenda.goal}</p>
          </div>
          <div className="agenda__row">
            <span className="label">Cover story</span>
            <p>{agenda.cover_story}</p>
          </div>
          <div className="agenda__row">
            <span className="label">Beats</span>
            <ol className="agenda__steps">
              {agenda.steps.map((s, i) => (
                <li key={i}>
                  <label>
                    <input type="checkbox" checked={done.has(i)} onChange={() => toggle(i)} />
                    <span>{s}</span>
                  </label>
                </li>
              ))}
            </ol>
          </div>
          <div className="agenda__row">
            <span className="label">Try saying</span>
            <ul className="agenda__lines">
              {agenda.lines.map((l, i) => (
                <li key={i}>“{l}”</li>
              ))}
            </ul>
          </div>
          <div className="agenda__row">
            <span className="label">If they push back</span>
            <dl className="agenda__obj">
              {agenda.objections.map((o, i) => (
                <div key={i}>
                  <dt>“{o.they_say}”</dt>
                  <dd>{o.you_say}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="agenda__row">
            <span className="label">Baseline listens for</span>
            <p className="agenda__watch">{agenda.watch.join(" · ")}</p>
          </div>
        </div>
      )}
    </section>
  );
}
