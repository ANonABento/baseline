// End-to-end smoke test of the live-call API with typed turns, run through the same reducer,
// notes mapping and report normalization the UI uses.
//   node scripts/live-smoke.ts [http://localhost:8000] [agent|scammer] [scenario]
import { buildNotes, verdictOf } from "../src/lib/notes.ts";
import { eventsFromBackend, replay } from "../src/lib/reports.ts";
import { INITIAL, sessionReducer, type SessionState } from "../src/lib/session.ts";
import type { ServerMsg } from "../src/lib/contract.ts";

const base = (process.argv[2] ?? "http://localhost:8000").replace(/\/$/, "");
const role = process.argv[3] ?? "agent";
const scenario = process.argv[4] ?? "account_takeover";
const TURNS =
  role === "agent"
    ? ["Thanks for calling First Harbor. Can you confirm your date of birth?", "I can't change anything until you verify. What's the ZIP on file?", "Why do you need the wire today?"]
    : ["Hi, this is Margaret Chen. I got a new phone, please change my number on file.", "I'm in a hurry, can we skip the security questions?", "I need to wire nine thousand dollars to a new account today, it's urgent."];

const cfg = await (await fetch(`${base}/api/config`)).json();
console.log(`config: tts=${cfg.tts} llm=${cfg.llm?.provider}/${cfg.llm?.model} active=${cfg.active_calls} queue=${cfg.queue_length}`);
const res = await fetch(`${base}/api/session`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ role, scenario, voice: "random" }) });
const sess = await res.json();
console.log("session:", sess.session_id, sess.ws_url);

let state: SessionState = { ...INITIAL, phase: "requesting" };
const counts: Record<string, number> = {};
let audioBytes = 0;
let turn = 0;
const t0 = Date.now();
const ws = new WebSocket(sess.ws_url);
ws.binaryType = "arraybuffer";
const log = (s: string) => console.log(`${((Date.now() - t0) / 1000).toFixed(1).padStart(5)}s ${s}`);

const done = new Promise<void>((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error("timeout")), 240_000);
  ws.onmessage = (m) => {
    if (typeof m.data !== "string") {
      audioBytes += (m.data as ArrayBuffer).byteLength;
      return;
    }
    const msg = JSON.parse(m.data) as ServerMsg;
    counts[msg.type] = (counts[msg.type] ?? 0) + 1;
    state = sessionReducer(state, { kind: "msg", msg, now: Date.now() });
    if (msg.type === "queue") log(`queue position=${msg.position} eta=${msg.eta_s}s`);
    if (msg.type === "call_started") log(`call_started role=${msg.role} scenario=${msg.scenario} voice=${msg.voice} customer=${msg.customer.name}`);
    if (msg.type === "transcript") log(`transcript [${msg.speaker}${msg.analyzed ? "" : ", not analyzed"} #${msg.utterance_id}] ${msg.text}`);
    if (msg.type === "signal") log(`signal ${msg.signal} u${msg.utterance_id} score=${msg.score.toFixed(2)} conf=${msg.confidence.toFixed(2)} ${msg.reason}`);
    if (msg.type === "alert") log(`alert ${msg.level} signals=${msg.signals.join(",")}`);
    if (msg.type === "error") log(`error ${msg.message}`);
    if (msg.type === "speaking" && msg.who === "ai" && msg.state === "end") {
      // the AI finished a turn: reply (typed), then hang up after the last one
      if (turn < TURNS.length) {
        const text = TURNS[turn++];
        setTimeout(() => {
          log(`> text: ${text}`);
          ws.send(JSON.stringify({ type: "text", text }));
        }, 600);
      } else if (turn === TURNS.length) {
        turn++;
        setTimeout(() => ws.send(JSON.stringify({ type: "hangup" })), 1500);
      }
    }
    if (msg.type === "call_ended") {
      log(`call_ended reason=${msg.reason} report=${msg.report_id} reveal=${JSON.stringify(msg.reveal)}`);
      clearTimeout(timer);
      resolve();
    }
  };
  ws.onclose = (e) => log(`socket closed ${e.code}`);
  ws.onerror = () => reject(new Error("socket error"));
});
await done;
ws.close();

const notes = buildNotes(state.lines, state.signals, state.evidence.items);
const v = verdictOf(state.peakAlert, notes, state.evidence.items);
console.log("\nevents:", JSON.stringify(counts), `audio=${(audioBytes / 32000).toFixed(1)}s`);
console.log(`live state: lines=${state.lines.length} notes=${notes.length} peak=${state.peak} verdict=${v.level} sayThis=${v.sayThis ?? "-"}`);

const reportId = state.ended?.report_id;
if (reportId) {
  const r = await fetch(`${base}/api/report/${reportId}`);
  const raw = await r.json();
  const rs = replay(eventsFromBackend(reportId, raw));
  const rn = buildNotes(rs.lines, rs.signals, rs.evidence.items);
  console.log(`report: HTTP ${r.status} lines=${rs.lines.length} signals=${rs.signals.length} notes=${rn.length} peak=${rs.peak} reveal=${rs.ended?.reveal.persona_label} duration=${((rs.endedAt ?? 0) / 1000).toFixed(1)}s backend_verdict=${raw.verdict?.level}`);
}
