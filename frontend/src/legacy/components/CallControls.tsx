import type { Clip } from "../../types";
import { IconMic, IconPlay, IconStop } from "./icons";
import { cx, Panel } from "./Panel";

/** "takeover_clone.wav" -> "Takeover clone" */
export function clipLabel(name: string): string {
  const base = name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  return base.charAt(0).toUpperCase() + base.slice(1);
}

export function CallControls({ clips, selected, onSelect, onReplay, onStop, onMic, mode, connected, micError, micLevel = 0 }: {
  clips: Clip[]; selected: string; onSelect: (c: string) => void; onReplay: () => void; onStop: () => void;
  onMic: () => void; mode: string; connected: boolean; micError: string | null; micLevel?: number;
}) {
  const busy = mode !== "idle";
  return (
    <Panel title="Call source">
      <label htmlFor="clip-picker" className="mb-1.5 block text-xs text-slate-400">Recorded call</label>
      <select
        id="clip-picker"
        className="mb-3 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500 disabled:opacity-60"
        value={selected}
        onChange={(e) => onSelect(e.target.value)}
        disabled={busy}
      >
        {clips.length === 0 && <option value="">{connected ? "No clips in data/demo/" : "Backend offline"}</option>}
        {clips.map((c) => (
          <option key={c.name} value={c.name}>
            {clipLabel(c.name)}{c.duration_s ? ` · ${Math.round(c.duration_s)}s` : ""}{c.has_transcript ? "" : " · no transcript"}
          </option>
        ))}
      </select>
      <div className="flex gap-2">
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-slate-700 px-3 py-2.5 text-sm font-semibold text-white hover:bg-slate-600"
          >
            <IconStop className="h-3.5 w-3.5" /> End call
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={onReplay}
              disabled={!connected || !selected}
              className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 py-2.5 text-sm font-semibold text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <IconPlay className="h-3.5 w-3.5" /> Start replay
            </button>
            <button
              type="button"
              onClick={onMic}
              disabled={!connected}
              className="flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2.5 text-sm font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
              title="Stream your microphone (16 kHz PCM)"
            >
              <IconMic className="h-4 w-4" /> Live mic
            </button>
          </>
        )}
      </div>
      {mode === "mic" && (
        <div className="mt-3 flex items-center gap-2 text-xs text-rose-200">
          <span className="live-pulse h-2 w-2 rounded-full bg-rose-500" /> Mic streaming
          <span className="ml-1 h-1.5 flex-1 overflow-hidden rounded bg-slate-800" aria-hidden>
            <span className={cx("block h-full rounded bg-emerald-400 transition-[width] duration-100")} style={{ width: `${Math.round(micLevel * 100)}%` }} />
          </span>
        </div>
      )}
      {micError && <p className="mt-2 text-xs text-rose-300" role="alert">{micError}</p>}
    </Panel>
  );
}
