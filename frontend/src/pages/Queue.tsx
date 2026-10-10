import { Baseline } from "../components/Baseline";
import type { SessionState } from "../lib/session";

function eta(s: number): string {
  if (s < 45) return "under a minute";
  const m = Math.round(s / 60);
  return `about ${m} min`;
}

export function Queue({ state, onCancel }: { state: SessionState; onCancel: () => void }) {
  const q = state.queue;
  return (
    <main className="queue" aria-live="polite">
      <div className="queue__top">
        <span className="label">{q ? "In line" : "Connecting"}</span>
        <h1 className="queue__pos">{q ? (q.position <= 1 ? "You're next" : `You're #${q.position}`) : "Finding a caller"}</h1>
        <p className="queue__eta">{q ? `Estimated wait ${eta(q.eta_s)}. Keep this tab open.` : "Reserving a line on the server."}</p>
      </div>
      <Baseline className="queue__line" pulse ariaLabel="Waiting for the call to connect" />
      <div className="queue__bottom">
        <button className="btn btn--ghost" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </main>
  );
}
