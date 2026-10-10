import { useEffect, useMemo, useRef, useState } from "react";
import { fmtTime } from "../analysis";
import type { Speaker } from "../lib/contract";
import { notesByLine, segmentText, TIER_GLYPH, type Note } from "../lib/notes";
import type { Line } from "../lib/session";

interface Props {
  lines: Line[];
  notes: Note[];
  /** sticky highlight (note id), lifted so the timeline can drive it */
  active: string | null;
  onActive: (id: string | null) => void;
  /** scroll request: utterance id + nonce */
  scrollTo?: { id: number; n: number } | null;
  who: Record<Speaker, string>;
  follow?: boolean;
  empty?: React.ReactNode;
}

export function NoteView({ note, hl, onClick, onHover }: { note: Note; hl: boolean; onClick?: () => void; onHover?: (on: boolean) => void }) {
  return (
    <button
      type="button"
      className={`note note--${note.tier} ${hl ? "note--hl" : ""}`}
      onClick={onClick}
      onMouseEnter={() => onHover?.(true)}
      onMouseLeave={() => onHover?.(false)}
      aria-pressed={hl}
    >
      <span className={`note__glyph tier-glyph tier-${note.tier}`} aria-label={note.tier}>
        {TIER_GLYPH[note.tier]}
      </span>
      <span className="note__title">{note.title}</span>
      {note.body && <span className="note__body">{note.body}</span>}
      {hl && note.source && <span className="note__src">Source: {note.source}</span>}
    </button>
  );
}

export function Transcript({ lines, notes, active, onActive, scrollTo, who, follow = true, empty }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const [hover, setHover] = useState<string | null>(null);
  const byLine = useMemo(() => notesByLine(notes), [notes]);
  const lit = hover ?? active;
  const litNote = notes.find((n) => n.id === lit);

  // follow the conversation unless the reader scrolled up
  useEffect(() => {
    const el = box.current;
    if (!el || !follow || !pinned.current) return;
    el.scrollTop = el.scrollHeight;
  }, [lines.length, notes.length, follow]);

  useEffect(() => {
    if (!scrollTo) return;
    const row = document.getElementById(`line-${scrollTo.id}`);
    row?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [scrollTo]);

  if (!lines.length) return <div className="transcript" ref={box}>{empty}</div>;

  return (
    <div
      className="transcript"
      ref={box}
      onScroll={(e) => {
        const el = e.currentTarget;
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
      }}
      aria-live="polite"
    >
      {lines.map((l) => {
        const ns = byLine.get(l.utterance_id) ?? [];
        const segs = segmentText(l.text, ns);
        const focus = litNote?.utterance_id === l.utterance_id;
        return (
          <div key={l.utterance_id} id={`line-${l.utterance_id}`} className={`tline tline--${l.speaker} ${focus ? "tline--focus" : ""}`}>
            <span className="tline__time">{fmtTime(l.t_start)}</span>
            <span className="tline__who">{who[l.speaker]}</span>
            <p className="tline__text">
              {segs.map((s) =>
                s.noteIds.length ? (
                  <span
                    key={s.start}
                    className={`span span--${s.tier} ${lit && s.noteIds.includes(lit) ? "span--hl" : ""}`}
                    onMouseEnter={() => setHover(s.noteIds[0])}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => onActive(active === s.noteIds[0] ? null : s.noteIds[0])}
                  >
                    {s.text}
                  </span>
                ) : (
                  <span key={s.start}>{s.text}</span>
                ),
              )}
            </p>
            <div className="tline__notes">
              {ns.map((n) => (
                <NoteView
                  key={n.id}
                  note={n}
                  hl={lit === n.id}
                  onClick={() => onActive(active === n.id ? null : n.id)}
                  onHover={(on) => setHover(on ? n.id : null)}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
