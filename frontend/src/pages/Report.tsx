import { useEffect, useMemo, useState } from "react";
import { fmtTime, SIGNAL_LABEL } from "../analysis";
import { Baseline } from "../components/Baseline";
import { TopBar } from "../components/Chrome";
import { Transcript } from "../components/Transcript";
import { fetchReport, isMockSetting } from "../lib/client";
import { buildNotes, spikesFromNotes, TIER_GLYPH, topEvidence, verdictOf, type Note } from "../lib/notes";
import { linkTo } from "../lib/prefs";
import { eventsFromBackend, listReports, loadLocal, replay, type Recorded } from "../lib/reports";
import type { SignalName } from "../types";
import { SCENARIO_LABEL } from "./Lobby";

const cap = (v: string) => v.charAt(0).toUpperCase() + v.slice(1);

type Loaded = { events: Recorded[]; raw: unknown; source: "backend" | "local" };

function download(name: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function Report({ id }: { id: string }) {
  const [data, setData] = useState<Loaded | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    const local = loadLocal(id);
    const useLocal = () => {
      if (!live) return;
      if (local) setData({ events: local.events, raw: local, source: "local" });
      else setMissing(true);
    };
    if (/^(mock|local)-/.test(id) || isMockSetting()) useLocal();
    else
      fetchReport(id).then(
        (raw) => live && setData({ events: eventsFromBackend(id, raw), raw, source: "backend" }),
        useLocal,
      );
    return () => {
      live = false;
    };
  }, [id]);

  const state = useMemo(() => (data ? replay(data.events) : null), [data]);
  const notes = useMemo(() => (state ? buildNotes(state.lines, state.signals, state.evidence.items) : []), [state]);
  const [active, setActive] = useState<string | null>(null);
  const [scrollTo, setScrollTo] = useState<{ id: number; n: number } | null>(null);

  if (missing)
    return (
      <>
        <TopBar rule />
        <div className="notice">
          <span className="label">Report {id}</span>
          <h1 className="section__title">This report isn't available.</h1>
          <p className="section__lede">It may have expired on the server, or it was recorded in another browser.</p>
          <p>
            <a className="btn" href="/call" onClick={linkTo("/call")}>
              Take a call
            </a>
          </p>
        </div>
      </>
    );
  if (!state || !data)
    return (
      <>
        <TopBar rule />
        <div className="notice">
          <span className="label">Loading report</span>
        </div>
      </>
    );

  const peakAlert = state.peakAlert ?? state.alert;
  const verdict = verdictOf(peakAlert, notes, state.evidence.items);
  const level = state.peak === "high" ? "alert" : state.peak === "caution" ? "watching" : "clear";
  const dur = state.startedAt != null && state.endedAt != null ? (state.endedAt - state.startedAt) / 1000 : 0;
  const axis = Math.max(30, dur, ...state.lines.map((l) => l.t_end + 2));
  const spikes = spikesFromNotes(notes, state.lines, axis).map((s) => {
    const n = notes.find((x) => x.id === s.noteId) as Note;
    return { id: s.noteId, x: s.x, tier: s.tier, label: `${TIER_GLYPH[n.tier]} ${n.title}` };
  });
  const reveal = state.ended?.reveal;
  const call = state.call;
  const lanes: SignalName[] = ["speaker", "spoof", "fraud", "prosody"];
  const peakOf = (lane: SignalName) => {
    const evs = state.signals.filter((s) => s.signal === lane && s.confidence > 0);
    if (!evs.length) return null;
    return evs.reduce((a, b) => (b.score > a.score ? b : a));
  };
  const top = topEvidence(state.evidence.items);
  const action =
    level === "clear"
      ? "No action needed. Nothing in this call deviated from the customer's baselines."
      : top?.suggested_agent_action || peakAlert?.suggested_action || "Verify the caller through the number on file before acting.";

  return (
    <>
      <TopBar rule>
        <nav className="topbar__nav">
          <a href="/reports" onClick={linkTo("/reports")} className="hide-sm">All reports</a>
        </nav>
      </TopBar>
      <main className="report">
        <header className="report__head">
          <div>
            <span className="label">
              Call report, {id}
              {data.source === "local" ? ", recorded in this browser" : ""}
            </span>
            <h1 className={`report__verdict report__verdict--${level}`}>
              {level === "alert" ? "Likely fraud" : level === "watching" ? "Needs a closer look" : "No fraud signals"}
            </h1>
          </div>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <button className="btn btn--ghost btn--small" type="button" onClick={() => download(`baseline-report-${id}.json`, data.raw)}>
              Download JSON
            </button>
            <a className="btn btn--small" href="/call" onClick={linkTo("/call")}>
              Take another call
            </a>
          </div>
        </header>

        <section className="report__section report__timeline" aria-label="Timeline">
          <span className="label">Timeline, {fmtTime(dur)}</span>
          <Baseline
            spikes={spikes}
            activeId={active}
            onSpike={(nid) => {
              setActive(nid);
              const n = notes.find((x) => x.id === nid);
              if (n) setScrollTo({ id: n.utterance_id, n: Date.now() });
            }}
            ariaLabel="Call timeline"
          />
        </section>

        <div className="report__grid">
          <section className="report__section" aria-label="Annotated transcript">
            <span className="label">Transcript</span>
            <Transcript
              lines={state.lines}
              notes={notes}
              active={active}
              onActive={setActive}
              scrollTo={scrollTo}
              follow={false}
              who={{ ai: "AI", visitor: "Visitor" }}
              empty={<p className="transcript__empty">Nobody spoke on this call.</p>}
            />
          </section>

          <aside>
            <section className="report__section">
              <span className="label">Recommended action</span>
              <p className="action">{action}</p>
              {verdict.sayThis && <p className="say__text" style={{ marginTop: "1rem", color: "var(--ink-2)" }}>{verdict.sayThis}</p>}
            </section>

            <section className="report__section">
              <span className="label">Reveal</span>
              <dl className="reveal">
                <dt>Caller</dt>
                <dd>{reveal?.persona_label || "Not disclosed"}</dd>
                <dt>Visitor</dt>
                <dd>{(reveal?.role ?? call?.role) === "scammer" ? "Played the scammer" : "Played the bank agent"}</dd>
                <dt>Scenario</dt>
                <dd>{SCENARIO_LABEL[reveal?.scenario ?? call?.scenario ?? ""] ?? (reveal?.scenario || call?.scenario || "Unknown")}</dd>
                <dt>Claimed</dt>
                <dd>{call ? `${call.customer.name} ${call.customer.account_mask}` : "Unknown"}</dd>
                <dt>Voice</dt>
                <dd>{[cap(reveal?.voice ?? call?.voice ?? ""), reveal?.tts].filter(Boolean).join(", ") || "Unknown"}</dd>
                <dt>Ended</dt>
                <dd>{state.ended?.reason.replace(/_/g, " ") ?? "Disconnected"}</dd>
              </dl>
            </section>

            <section className="report__section">
              <span className="label">Signals, peak per detector</span>
              <table className="sigtable">
                <thead>
                  <tr>
                    <th>Detector</th>
                    <th>Reason</th>
                    <th>Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {lanes.map((l) => {
                    const p = peakOf(l);
                    return (
                      <tr key={l}>
                        <td>{SIGNAL_LABEL[l]}</td>
                        <td>{p?.reason ?? "No opinion"}</td>
                        <td style={{ color: p && p.score >= 0.5 ? "var(--red)" : p && p.score >= 0.25 ? "var(--amber)" : undefined }}>
                          {p ? p.score.toFixed(2) : "–"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>

            {state.evidence.items.length > 0 && (
              <section className="report__section">
                <span className="label">Evidence{state.evidence.model ? `, ${state.evidence.model}` : ""}</span>
                <div className="evidence">
                  {state.evidence.items.map((e) => (
                    <div className="evidence__item" key={e.id}>
                      <span className="evidence__name">
                        <span className={`tier-glyph tier-${e.severity === "high" ? "flag" : e.severity === "medium" ? "watch" : "noted"}`}>
                          {e.severity === "high" ? "■" : e.severity === "medium" ? "◆" : "◇"}
                        </span>
                        {e.name}
                      </span>
                      {e.quote && <span className="evidence__quote">{e.quote}</span>}
                      {e.source && (
                        <span className="label">
                          {e.source_url ? (
                            <a className="link" href={e.source_url} target="_blank" rel="noreferrer">
                              {e.source}
                            </a>
                          ) : (
                            e.source
                          )}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}
          </aside>
        </div>
      </main>
    </>
  );
}

export function Reports() {
  const list = listReports();
  return (
    <>
      <TopBar rule />
      <main className="report">
        <span className="label">Reports recorded in this browser</span>
        <h1 className="section__title" style={{ marginTop: "0.75rem" }}>
          Recent calls
        </h1>
        {list.length ? (
          <div className="reports-list">
            {list.map((r) => (
              <a key={r.id} href={`/report/${r.id}`} onClick={linkTo(`/report/${r.id}`)}>
                <span className="mono">{new Date(r.savedAt).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
                <span className="mono">{fmtTime(r.duration)}</span>
                <span>
                  {SCENARIO_LABEL[r.scenario] ?? r.scenario}, {r.role === "scammer" ? "you played the scammer" : "you played the agent"}
                </span>
                <span className={`tier-glyph ${r.peak === "high" ? "tier-flag" : r.peak === "caution" ? "tier-watch" : "tier-noted"}`}>
                  {r.peak === "high" ? "■ Alert" : r.peak === "caution" ? "◆ Watch" : "◇ Clear"}
                </span>
              </a>
            ))}
          </div>
        ) : (
          <p className="section__lede">
            No calls yet.{" "}
            <a className="link" href="/call" onClick={linkTo("/call")}>
              Take one
            </a>{" "}
            and its report will show up here.
          </p>
        )}
      </main>
    </>
  );
}
