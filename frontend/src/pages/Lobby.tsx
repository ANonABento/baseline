import { useEffect, useState } from "react";
import { TopBar } from "../components/Chrome";
import { Viewport } from "../components/Viewport";
import { loadConfig } from "../lib/client";
import type { AppConfig, Option, ScenarioOption, SessionRequest } from "../lib/contract";
import { cameraError, currentCamera, micMeter, startCamera, stopCamera } from "../lib/media";
import { linkTo } from "../lib/prefs";
import { listReports } from "../lib/reports";

const ROLES: { id: SessionRequest["role"]; label: string; hint: string }[] = [
  { id: "client", label: "Be the client", hint: "A scammer is about to call you. Can you tell? Baseline can." },
  { id: "scammer", label: "Be the scammer", hint: "Call First Harbor pretending to be Kevin. Try to get past Baseline." },
  { id: "candidate", label: "Pressure simulation", hint: "You're the bank agent; the caller's pressure rises. Your delivery and decisions feed a Digital Twin and a signed credential. Needs the live backend." },
  { id: "random", label: "Random", hint: "You'll find out which side you're on when the call connects." },
];

export const SCENARIO_LABEL: Record<string, string> = {
  fake_bank: "First Harbor 'fraud department'",
  grandchild: "Kevin in trouble (voice clone)",
  irs: "IRS back taxes",
  tech_support: "Tech support refund",
  account_takeover: "Account takeover",
  grandparent: "Grandparent / coached",
  grandparent_coached: "Grandparent / coached",
  safe_account: "Safe account",
  verification_evasion: "Verification evasion",
};

function Meter({ level }: { level: number }) {
  const n = 24;
  const lit = Math.round(level * n);
  return (
    <div className="meter" aria-label={`Mic level ${Math.round(level * 100)}%`}>
      {Array.from({ length: n }, (_, i) => (
        <i key={i} className={i < lit ? (i > n * 0.8 ? "hot" : "on") : ""} />
      ))}
    </div>
  );
}

interface Props {
  onJoin: (req: SessionRequest) => void;
  error: string | null;
}

export function Lobby({ onJoin, error }: Props) {
  const [cfg, setCfg] = useState<{ mock: boolean; config: AppConfig } | null>(null);
  const [cfgErr, setCfgErr] = useState<string | null>(null);
  const [role, setRole] = useState<SessionRequest["role"]>("client");
  const [scenario, setScenario] = useState("random");
  const [voice, setVoice] = useState("random");
  const [video, setVideo] = useState<HTMLVideoElement | null>(currentCamera());
  const [camErr, setCamErr] = useState<string | null>(null);
  const [camOn, setCamOn] = useState(true);
  const [mic, setMic] = useState(0);
  const [micErr, setMicErr] = useState<string | null>(null);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [camId, setCamId] = useState<string>("");
  const [micId, setMicId] = useState<string>("");
  const [recordVoice, setRecordVoice] = useState(false);

  useEffect(() => {
    loadConfig().then(setCfg, (e: Error) => setCfgErr(e.message));
  }, []);

  useEffect(() => {
    if (!camOn) {
      stopCamera();
      setVideo(null);
      return;
    }
    let live = true;
    startCamera(camId || undefined).then(
      (v) => {
        if (!live) return;
        setVideo(v);
        setCamErr(null);
        navigator.mediaDevices.enumerateDevices().then(setDevices, () => undefined);
      },
      (e) => live && setCamErr(cameraError(e)),
    );
    return () => {
      live = false;
    };
  }, [camOn, camId]);

  useEffect(() => {
    let stop: (() => void) | null = null;
    let live = true;
    micMeter(setMic, micId || undefined).then(
      (s) => {
        if (live) {
          stop = s;
          setMicErr(null);
          navigator.mediaDevices.enumerateDevices().then(setDevices, () => undefined);
        } else s();
      },
      () => live && setMicErr("Microphone blocked. You can still type."),
    );
    return () => {
      live = false;
      stop?.();
    };
  }, [micId]);

  const allScenarios: ScenarioOption[] = cfg?.config.scenarios ?? [];
  // scenarios for the chosen side (old backends send no role: show them all)
  const scenarios = role === "random" ? [] : allScenarios.filter((s) => !s.role || s.role === role);
  const pickRole = (r: SessionRequest["role"]) => {
    setRole(r);
    setScenario("random");
  };
  const brief = scenarios.find((s) => s.id === scenario)?.brief;
  const voices: Option[] = cfg?.config.voices ?? [];
  const cams = devices.filter((d) => d.kind === "videoinput");
  const mics = devices.filter((d) => d.kind === "audioinput");
  const recent = listReports().slice(0, 3);
  const queue = cfg ? cfg.config.queue_length : 0;

  return (
    <>
      <TopBar rule>
        {cfg?.mock && <span className="mode-chip" title="Backend unreachable: simulated calls">Demo mode</span>}
      </TopBar>
      <main className="lobby">
        <section className="preview" aria-label="Your camera and microphone">
          <div className="preview__frame">
            <span className="label preview__tag">You{video ? "" : ", camera off"}</span>
            <Viewport source="video" video={video} label="Your camera preview, stylized" />
          </div>
          <div className="checks">
            <span className="label">Camera</span>
            {cams.length > 1 ? (
              <select value={camId} onChange={(e) => setCamId(e.target.value)} aria-label="Camera">
                {cams.map((d) => (
                  <option key={d.deviceId} value={d.deviceId}>
                    {d.label || "Camera"}
                  </option>
                ))}
              </select>
            ) : (
              <span className="checks__status" style={{ color: camErr ? "var(--amber)" : "var(--ink-2)" }}>
                {camErr ?? (video ? "On" : camOn ? "Starting" : "Off")}
              </span>
            )}
            <button type="button" className="link" onClick={() => setCamOn((v) => !v)}>
              {camOn ? "Turn off" : "Turn on"}
            </button>
            <span className="label">Mic</span>
            {micErr ? <span className="checks__status" style={{ color: "var(--amber)" }}>{micErr}</span> : <Meter level={mic} />}
            {mics.length > 1 ? (
              <select value={micId} onChange={(e) => setMicId(e.target.value)} aria-label="Microphone">
                {mics.map((d) => (
                  <option key={d.deviceId} value={d.deviceId}>
                    {d.label || "Microphone"}
                  </option>
                ))}
              </select>
            ) : (
              <span />
            )}
          </div>
          <p className="privacy">Your camera never leaves your device. Baseline analyzes voice and words only.</p>
          <label className="option option--check">
            <input type="checkbox" checked={recordVoice} onChange={(e) => setRecordVoice(e.target.checked)} />
            <span className="option__mark" />
            <span className="option__text">
              Save my voice with the call report
              <span className="option__hint">The caller's voice is always saved. Reports are public.</span>
            </span>
          </label>
        </section>

        <section className="config" aria-label="Call setup">
          <div>
            <h1 className="config__title">Take a call</h1>
            <p className="config__sub">First Harbor runs Baseline on both sides of the call: in its call center and in its app on your phone. Calls last up to four minutes.</p>
          </div>

          <fieldset className="field">
            <legend className="label">Your side</legend>
            <div className="options">
              {ROLES.map((r) => (
                <label className="option" key={r.id}>
                  <input type="radio" name="role" value={r.id} checked={role === r.id} onChange={() => pickRole(r.id)} disabled={r.id === "candidate" && !!cfg?.mock} />
                  <span className="option__mark" />
                  <span className="option__text">
                    {r.label}
                    <span className="option__hint">{r.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          {scenarios.length > 0 && (
            <fieldset className="field">
              <legend className="label">{role === "scammer" ? "Your mission" : "Who calls you"}</legend>
              <div className="chips">
                {[{ id: "random", label: role === "scammer" ? "Surprise me" : "Don't tell me" }, ...scenarios].map((s) => (
                  <label className="chip" key={s.id}>
                    <input type="radio" name="scenario" value={s.id} checked={scenario === s.id} onChange={() => setScenario(s.id)} />
                    {s.label}
                  </label>
                ))}
              </div>
              {brief && <p className="field__hint">{brief}</p>}
            </fieldset>
          )}

          <details className="advanced">
            <summary className="label">Advanced</summary>
            <fieldset className="field">
              <legend className="label">{role === "scammer" ? "Bank agent voice" : "Caller voice"}</legend>
              <div className="chips">
                {[{ id: "random", label: "Match the scenario" }, ...voices].map((v) => (
                  <label className="chip" key={v.id}>
                    <input type="radio" name="voice" value={v.id} checked={voice === v.id} onChange={() => setVoice(v.id)} />
                    {v.label}
                  </label>
                ))}
              </div>
            </fieldset>
          </details>

          <div className="join">
            <button className="btn btn--big" type="button" disabled={!cfg} onClick={() => onJoin({ role, scenario, voice, record_audio: recordVoice })}>
              Join call
            </button>
            {(error || cfgErr) && <p className="warning" role="alert">{error ?? `Backend unreachable: ${cfgErr}`}</p>}
            <div className="join__meta">
              <span className="label">
                {cfg ? `${cfg.config.active_calls} live, ${queue} waiting` : "Checking line"}
              </span>
              <span className="label">{cfg ? (cfg.mock ? "Simulated calls" : `${cfg.config.llm.model}`) : ""}</span>
            </div>
            {recent.length > 0 && (
              <div className="recent">
                <span className="label">Your recent calls</span>
                {recent.map((r) => (
                  <a key={r.id} href={`/report/${r.id}`} onClick={linkTo(`/report/${r.id}`)}>
                    <span className={`tier-glyph ${r.peak === "high" ? "tier-flag" : r.peak === "caution" ? "tier-watch" : "tier-noted"}`}>
                      {r.peak === "high" ? "■" : r.peak === "caution" ? "◆" : "◇"}
                    </span>
                    {SCENARIO_LABEL[r.scenario] ?? r.scenario}, {new Date(r.savedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                  </a>
                ))}
              </div>
            )}
          </div>
        </section>
      </main>
    </>
  );
}
