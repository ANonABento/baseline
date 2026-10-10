import { fmtTime } from "../analysis";
import { BASELINE_N, DECISION_LABEL, Z_FIRE, Z_LABEL, type TwinView } from "../lib/twin";

const HEDGE = "Change vs this person's own earlier delivery. Not stress, honesty or skill; calibration not established.";

function ZBar({ label, z }: { label: string; z: number }) {
  const w = Math.min(50, (Math.abs(z) / 4) * 50);
  const hot = Math.abs(z) >= Z_FIRE;
  return (
    <div className="zbar" title={`${label}: ${z > 0 ? "+" : ""}${z.toFixed(1)} vs own baseline`}>
      <span className="label">{label}</span>
      <span className="zbar__track">
        <i className={hot ? "hot" : ""} style={z >= 0 ? { left: "50%", width: `${w}%` } : { left: `${50 - w}%`, width: `${w}%` }} />
      </span>
      <span className="num zbar__v">{z > 0 ? "+" : ""}{z.toFixed(1)}</span>
    </div>
  );
}

/** Live Digital Twin of the person on the call: baseline, current delivery, pressure applied, decisions, timeline. */
export function TwinPanel({ twin, duration }: { twin: TwinView; duration: number }) {
  const ch = twin.latest?.change;
  return (
    <section className="twin" aria-label="Digital twin">
      <header className="twin__head">
        <span className="label">Digital twin</span>
        <span className={`twin__pressure twin__pressure--${twin.pressureNow ?? 0}`}>
          {twin.pressureNow ? `Pressure ${twin.pressureNow} of 3` : "No pressure yet"}
        </span>
      </header>

      {!twin.baselineReady ? (
        <p className="twin__note">Learning this person's normal ({twin.baselineN} of {BASELINE_N} turns)…</p>
      ) : twin.latest?.status === "insufficient_evidence" ? (
        <p className="twin__note">Not enough clear audio in the last turn.</p>
      ) : (
        <>
          <div className="twin__gauge" title={HEDGE}>
            <span className="label">Change vs earlier delivery</span>
            <span className="twin__gauge-track">
              <i style={{ width: `${Math.round((ch ?? 0) * 100)}%` }} />
            </span>
            <span className="num">{ch == null ? "–" : ch.toFixed(2)}</span>
          </div>
          {twin.markers.length > 0 && (
            <div className="chips" aria-label="Delivery markers">
              {twin.markers.map((m) => (
                <span className="chip chip--static" key={m}>{m}</span>
              ))}
            </div>
          )}
          {twin.z && (
            <div className="twin__z">
              {Object.entries(Z_LABEL).map(([k, label]) => (twin.z![k] == null ? null : <ZBar key={k} label={label} z={twin.z![k]} />))}
            </div>
          )}
        </>
      )}

      <div className="twin__row">
        <span className="label">Speech rate</span>
        <span className="num">{twin.latest?.wps != null ? `${twin.latest.wps.toFixed(1)} words/s` : "–"}</span>
        <span className="label">Response latency</span>
        <span className="num">{twin.latest?.latency_s != null ? `${twin.latest.latency_s.toFixed(1)} s` : "–"}</span>
        <span className="label">Largest change (|z|)</span>
        <span className="num">{twin.latest?.maxAbsZ != null ? twin.latest.maxAbsZ.toFixed(1) : "–"}</span>
        <span className="label">Pausing</span>
        <span className="num">{twin.latest?.pauseFrac != null ? `${Math.round(twin.latest.pauseFrac * 100)}%` : "–"}</span>
      </div>

      {twin.emotion && (
        <div className="twin__emotion" title="Acted-speech probe; uncalibrated on real speech. Side information only.">
          <span className="label">Emotion estimate (acted-speech probe)</span>
          {twin.emotion.map((e) => (
            <span className="num" key={e.label}>{e.label} {Math.round(e.p * 100)}%</span>
          ))}
        </div>
      )}

      <TwinTimeline twin={twin} duration={duration} />

      <div className="twin__decisions">
        <span className="label">Detected phrases (keyword-based, not verdicts)</span>
        {twin.decisions.length === 0 ? (
          <span className="twin__note">None yet.</span>
        ) : (
          <ul>
            {twin.decisions.map((d, i) => (
              <li key={i}>
                <span className="num">{fmtTime(d.t)}</span> {DECISION_LABEL[d.event]}
              </li>
            ))}
          </ul>
        )}
      </div>
      <p className="twin__hedge">{HEDGE}</p>
    </section>
  );
}

/** x = call time; top row = AI turns by pressure level; bottom row = person turns coloured by delivery change; flags = decisions. */
export function TwinTimeline({ twin, duration }: { twin: TwinView; duration: number }) {
  const x = (t: number) => `${Math.min(100, Math.max(0, (t / Math.max(duration, 1)) * 100))}%`;
  return (
    <div className="ttl" role="img" aria-label="Pressure and delivery timeline">
      <div className="ttl__row">
        {twin.turns.length >= 0 &&
          twin.turns.map((t) =>
            t.pressure ? <i key={`p${t.utterance_id}`} className={`ttl__p ttl__p--${t.pressure}`} style={{ left: x(t.t) }} /> : null,
          )}
      </div>
      <div className="ttl__row">
        {twin.turns.map((t) => (
          <i
            key={t.utterance_id}
            className="ttl__turn"
            title={`${fmtTime(t.t)} change ${t.change == null ? "n/a" : t.change.toFixed(2)}`}
            style={{ left: x(t.t), width: `max(6px, ${x(Math.max(t.t_end - t.t, 0.5))})`, opacity: t.change == null ? 0.25 : 0.35 + 0.65 * t.change }}
          />
        ))}
        {twin.decisions.map((d, i) => (
          <b key={i} className="ttl__flag" style={{ left: x(d.t) }} title={DECISION_LABEL[d.event]} />
        ))}
      </div>
    </div>
  );
}
