import { useEffect, useState } from "react";
import { fetchCredential } from "../lib/client";
import { changeByPressure, type TwinView } from "../lib/twin";

type Obj = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const f = (v: unknown, unit = "") => (typeof v === "number" ? `${v}${unit}` : "–");

/** End-of-call summary (report.behaviour) + the signed credential: download, offline verify page, issuer DID, claims verbatim. */
export function BehaviourSummary({ id, behaviour, twin }: { id: string; behaviour: Obj; twin: TwinView }) {
  const [cred, setCred] = useState<Obj | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let live = true;
    fetchCredential(id).then(
      (c) => live && setCred(c as Obj),
      () => live && setErr(true),
    );
    return () => {
      live = false;
    };
  }, [id]);
  const b = behaviour;
  const rec = b.recovery_latency ?? {};
  const byLevel = Object.entries(b.delivery_change_by_pressure_level ?? {}) as [string, Obj][];
  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(cred, null, 1)], { type: "application/json" }));
    a.download = `baseline-credential-${id}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  const levels = byLevel.length ? byLevel.map(([k, v]) => ({ level: Number(k), mean: v.mean_max_abs_z as number, n: v.n as number })) : changeByPressure(twin.turns);
  return (
    <>
      <section className="report__section">
        <span className="label">Behavioural signals (exploratory)</span>
        <dl className="reveal">
          <dt>Tone drift</dt>
          <dd>pitch {f(b.tone_drift?.pitch_z_per_min, " z/min")}, loudness {f(b.tone_drift?.loudness_z_per_min, " z/min")}, max |z| {f(b.tone_drift?.max_abs_z)}</dd>
          <dt>Speech rate</dt>
          <dd>{f(b.speech_rate?.words_per_s_mean, " words/s")} mean, trend {f(b.speech_rate?.words_per_s_trend_per_min, " words/s per min")}</dd>
          <dt>Hesitation</dt>
          <dd>{f(b.hesitation?.fillers_per_100_words)} fillers per 100 words, pausing {typeof b.hesitation?.pause_frac_mean === "number" ? `${Math.round(b.hesitation.pause_frac_mean * 100)}%` : "–"}</dd>
          <dt>Response latency</dt>
          <dd>{f(b.response_latency_s?.mean, " s")} mean, {f(b.response_latency_s?.max, " s")} max (n={f(b.response_latency_s?.n)})</dd>
          <dt>De-escalation latency</dt>
          <dd>
            {rec.status === "recovered"
              ? `${f(rec.latency_s, " s")} from the peak at ${f(rec.peak_at_s, " s")} to back within own range`
              : rec.status === "not_recovered_in_call"
                ? "Not back within own range before the call ended"
                : "No peak over threshold"}
          </dd>
          <dt>Turns</dt>
          <dd>{b.n_turns_analysed} analysed, {b.n_turns_with_baseline} with a baseline (n is small; no CI is meaningful)</dd>
        </dl>
        {levels.length > 0 && (
          <table className="sigtable" aria-label="Delivery change by scripted pressure level">
            <thead>
              <tr><th>Pressure level</th><th>Mean max |z|</th><th>n</th></tr>
            </thead>
            <tbody>
              {levels.map((l) => (
                <tr key={l.level}><td>{l.level}</td><td className="num">{l.mean.toFixed(2)}</td><td className="num">{l.n}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="report__section">
        <span className="label">Decisions (keyword-detected phrases)</span>
        <p className="twin__note">
          {b.interaction?.verification_attempts ?? 0} verification attempts, {b.interaction?.refusals ?? 0} refusals, {b.interaction?.compliance_phrases ?? 0} compliance phrases,{" "}
          {b.interaction?.talk_over_count ?? 0} talk-overs.
        </p>
      </section>

      <section className="report__section" aria-label="Credential">
        <span className="label">Verifiable credential</span>
        {cred ? (
          <>
            <dl className="reveal">
              <dt>Issuer</dt>
              <dd className="mono-wrap">{cred.payload.issuer}</dd>
              <dt>Issued</dt>
              <dd>{cred.payload.issued_at}</dd>
              <dt>Report SHA-256</dt>
              <dd className="mono-wrap">{cred.payload.report_sha256}</dd>
              <dt>Claims</dt>
              <dd>{cred.payload.claims}</dd>
            </dl>
            <p style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "1rem" }}>
              <button className="btn btn--small" type="button" onClick={download}>Download credential</button>
              <a className="btn btn--ghost btn--small" href="/verify.html" target="_blank" rel="noreferrer">Verify offline</a>
            </p>
            <p className="twin__note">Verification runs in your browser against the public key inside the issuer DID. It proves who signed which observations; it does not prove skill, honesty or suitability.</p>
          </>
        ) : (
          <p className="twin__note">{err ? "No credential for this report (it is issued by a running backend when the call ends)." : "Loading credential…"}</p>
        )}
      </section>
    </>
  );
}
