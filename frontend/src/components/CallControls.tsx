import type { Clip } from "../types";
import { Panel } from "./Panel";

export function CallControls({ clips, selected, onSelect, onReplay, onStop, onMic, mode, connected, micError }: {
  clips: Clip[]; selected: string; onSelect: (c: string) => void; onReplay: () => void; onStop: () => void;
  onMic: () => void; mode: string; connected: boolean; micError: string | null;
}) {
  const busy = mode !== "idle";
  return (
    <Panel title="Call source">
      <label className="mb-1 block text-xs text-slate-500">Replay a recorded call</label>
      <select
        className="mb-3 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none focus:border-indigo-500"
        value={selected}
        onChange={(e) => onSelect(e.target.value)}
        disabled={busy}
      >
        {clips.length === 0 && <option value="">No clips in data/demo/</option>}
        {clips.map((c) => (
          <option key={c.name} value={c.name}>
            {c.name} {c.duration_s ? `· ${c.duration_s}s` : ""} {c.has_transcript ? "" : "· no transcript"}
          </option>
        ))}
      </select>
      <div className="flex gap-2">
        {busy ? (
          <button onClick={onStop} className="flex-1 rounded-lg bg-slate-700 px-3 py-2 text-sm font-semibold hover:bg-slate-600">
            ■ Stop
          </button>
        ) : (
          <>
            <button
              onClick={onReplay}
              disabled={!connected || !selected}
              className="flex-1 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-40"
            >
              ▶ Start replay
            </button>
            <button
              onClick={onMic}
              disabled={!connected}
              className="rounded-lg border border-slate-700 px-3 py-2 text-sm font-semibold hover:bg-slate-800 disabled:opacity-40"
              title="Stream your microphone (16 kHz PCM)"
            >
              🎙 Live mic
            </button>
          </>
        )}
      </div>
      {mode === "mic" && <p className="mt-2 text-xs text-rose-300">● Live mic streaming…</p>}
      {micError && <p className="mt-2 text-xs text-rose-400">{micError}</p>}
    </Panel>
  );
}
