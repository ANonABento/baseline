import { Baseline, type LineSpike } from "../components/Baseline";
import { TopBar } from "../components/Chrome";
import { Viewport } from "../components/Viewport";
import { linkTo } from "../lib/prefs";

const STATS = [
  {
    fig: "$7.7B",
    text: "lost by Americans over 60 to reported cybercrime in 2025, up 59% in a year. The average loss was $38,500.",
    src: "FBI IC3 Internet Crime Report 2025",
    url: "https://www.ic3.gov/AnnualReport/Reports/2025_IC3Report.pdf",
  },
  {
    fig: "1,300%",
    text: "rise in deepfake fraud attempts on contact centers in 2024, from about one a month to seven a day.",
    src: "Pindrop Voice Intelligence Report 2025 (vendor data)",
    url: "https://cioinfluence.com/security/pindrops-2025-voice-intelligence-security-report-reveals-1300-surge-in-deepfake-fraud/",
  },
  {
    fig: "$16B",
    text: "reported lost to fraud in 2025, a record. Bank impersonators were the costliest business impersonation scam.",
    src: "FTC, June 2026",
    url: "https://ftc.gov/news-events/news/press-releases/2026/06/ftc-data-show-people-reported-losing-3-point-5-billion-imposter-scams-2025",
  },
];

const ROWS: { title: string; body: string; tech: string; spikes: LineSpike[] }[] = [
  {
    title: "The enrolled voice",
    body: "Does this voice match the customer's voiceprint on file? A clone can get close. It rarely gets close enough.",
    tech: "Speaker verification",
    spikes: [{ id: "a", x: 0.62, tier: "watch" }],
  },
  {
    title: "Real human audio",
    body: "Does the audio carry the artifacts of synthetic speech or a voice changer, window by window?",
    tech: "Spoof detection",
    spikes: [{ id: "b", x: 0.38, tier: "flag" }],
  },
  {
    title: "Legitimate requests",
    body: "Is the caller following a known fraud script: a new phone number, then an urgent wire? Every flag cites the line and the source.",
    tech: "Local LLM + fraud playbook",
    spikes: [
      { id: "c", x: 0.3, tier: "noted" },
      { id: "d", x: 0.72, tier: "flag" },
    ],
  },
];

function Code() {
  return (
    <pre className="code" aria-label="WebSocket event example">
      <span className="c">{"// WS /ws/session/{id}  server → agent desktop\n"}</span>
      {"{ "}<span className="k">"type"</span>: <span className="s">"transcript"</span>, <span className="k">"utterance_id"</span>: 4,{"\n"}
      {"  "}<span className="k">"speaker"</span>: <span className="s">"ai"</span>, <span className="k">"text"</span>: <span className="s">"I need to wire nine thousand dollars…"</span>{" }\n\n"}
      {"{ "}<span className="k">"type"</span>: <span className="s">"signal"</span>, <span className="k">"signal"</span>: <span className="s">"spoof"</span>, <span className="k">"score"</span>: 0.78,{"\n"}
      {"  "}<span className="k">"reason"</span>: <span className="s">"Synthetic-speech artifacts in 78% of windows"</span>{" }\n\n"}
      {"{ "}<span className="k">"type"</span>: <span className="s">"alert"</span>, <span className="k">"level"</span>: <span className="r">"high"</span>,{"\n"}
      {"  "}<span className="k">"signals"</span>: [<span className="s">"spoof"</span>, <span className="s">"speaker"</span>, <span className="s">"fraud"</span>],{"\n"}
      {"  "}<span className="k">"suggested_action"</span>: <span className="s">"Call back on the number on file."</span>{" }"}
    </pre>
  );
}

export function Landing() {
  return (
    <div className="landing">
      <TopBar>
        <nav className="topbar__nav">
          <a href="#banks" className="hide-sm">For Banks</a>
          <a href="/reports" onClick={linkTo("/reports")} className="hide-sm">Reports</a>
        </nav>
      </TopBar>

      <section className="hero">
        <div className="hero__head">
          <Viewport source="head" zoom={1.2} label="An unidentified caller, rendered as a shifting field of glyphs" />
        </div>
        <Baseline className="hero__line" ambient interactive ariaLabel="The baseline: flat when a call is normal, spiking when something deviates" />
        <div className="hero__copy">
          <span className="label">Incoming call, unverified</span>
          <h1 className="hero__title">Is this caller real?</h1>
          <p className="hero__sub">
            Take a call from an AI caller. Baseline listens alongside you and flags the moment the voice, or the story, stops adding up.
          </p>
          <div className="hero__actions">
            <a className="btn btn--big" href="/call" onClick={linkTo("/call")}>
              Take a call
            </a>
            <a className="link hero__down" href="#banks">
              For Banks <span aria-hidden>↓</span>
            </a>
          </div>
        </div>
      </section>

      <section className="section" id="banks" aria-labelledby="problem-title">
        <div className="section__head">
          <span className="label">The problem</span>
          <div>
            <h2 className="section__title" id="problem-title">
              A voice on the phone is no longer proof of anything.
            </h2>
            <p className="section__lede">
              Banks still let customers move money over the phone. A thirty-second clone now passes for them, and scammers coach real
              customers while they're on the line with the bank.
            </p>
          </div>
        </div>
        <div className="stats">
          {STATS.map((s) => (
            <figure className="stat" key={s.fig}>
              <span className="stat__fig">{s.fig}</span>
              <p className="stat__text">{s.text}</p>
              <span className="stat__src label">
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.src}
                </a>
              </span>
            </figure>
          ))}
        </div>
      </section>

      <section className="section" aria-labelledby="how-title">
        <div className="section__head">
          <span className="label">How it works</span>
          <div>
            <h2 className="section__title" id="how-title">
              Three baselines, checked on every line.
            </h2>
            <p className="section__lede">Baseline knows what each customer sounds like and how legitimate calls go. It shows the agent when a call drifts from either.</p>
          </div>
        </div>
        <div className="baselines">
          {ROWS.map((r) => (
            <div className="bl-row" key={r.title}>
              <Baseline className="bl-row__glyph" spikes={r.spikes} ariaLabel={`${r.title} deviation`} />
              <h3 className="bl-row__title">{r.title}</h3>
              <p className="bl-row__body">{r.body}</p>
              <span className="label bl-row__tech">{r.tech}</span>
            </div>
          ))}
        </div>
        <p className="fusion-note">
          <strong>No single signal is trusted.</strong> A clone can fool voice ID. The alert escalates when independent baselines agree.
        </p>
      </section>

      <section className="section" aria-labelledby="proof-title">
        <div className="section__head">
          <span className="label">Proof</span>
          <h2 className="proof__statement" id="proof-title">
            On 42 calls it had never seen, Baseline caught 19 of 21 scams and raised no false alarms, offline, on one laptop.
          </h2>
        </div>
        <div className="proof__figs">
          <div className="proof__fig">
            <span className="label">Scams detected</span>
            <div className="proof__value">90.5%</div>
          </div>
          <div className="proof__fig">
            <span className="label">False alarms</span>
            <div className="proof__value">0%</div>
          </div>
          <div className="proof__fig">
            <span className="label">Runs on</span>
            <div className="proof__value">One laptop</div>
          </div>
        </div>
        <p className="proof__fine">
          Held-out transcript set of 21 scam and 21 legitimate calls, kept out of tuning. Fraud analysis by a 4B-parameter model (qwen3.5:4b
          via Ollama) on an M5 MacBook, with no network. Call audio never has to leave the bank.
        </p>
      </section>

      <section className="section" aria-labelledby="api-title">
        <div className="api">
          <div>
            <span className="label">API</span>
            <h2 className="section__title" id="api-title" style={{ marginTop: "1rem" }}>
              Stream the call in. Get evidence out.
            </h2>
            <p className="section__lede">
              Send 16 kHz audio over a WebSocket. Your agent desktop receives the transcript, each signal with its reason, and a single alert
              with the action to take. Every call ends with a report.
            </p>
            <div className="api__list">
              <div><span className="label">transcript</span>Speaker-tagged lines as they're spoken</div>
              <div><span className="label">signal</span>Voice match, synthetic audio, fraud pattern, pressure</div>
              <div><span className="label">alert</span>Fused level, agreeing signals, citations</div>
              <div><span className="label">report</span>GET /api/report/:id after the call</div>
            </div>
          </div>
          <Code />
        </div>
      </section>

      <footer className="footer">
        <div>
          <p>Baseline. A real-time fraud co-pilot for bank call centers. Built at Building from the Farm, October 2026.</p>
          <p style={{ marginTop: "0.5rem" }}>
            Head model: Lee Perry-Smith, CC-BY 3.0, via the three.js examples. Statistics link to their sources.
          </p>
        </div>
        <div className="footer__links">
          <a href="/call" onClick={linkTo("/call")}>Take a call</a>
          <a href="/reports" onClick={linkTo("/reports")}>Reports</a>
        </div>
      </footer>
    </div>
  );
}
