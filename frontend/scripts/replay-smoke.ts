// End-to-end smoke test against a running backend: replays each demo clip over the same
// WebSocket the dashboard uses and runs the events through the dashboard's analysis logic.
//   node scripts/replay-smoke.ts [ws://localhost:8000/ws/call] [clip ...]
import { EMPTY_EVIDENCE, buildTimeline, lineTriggers, mergeEvidence, type EvidenceState } from "../src/analysis.ts";
import type { AlertEvent, ServerEvent, SignalEvent, TranscriptEvent } from "../src/types.ts";

const url = process.argv[2] ?? "ws://localhost:8000/ws/call";
const http = url.replace(/^ws/, "http").replace(/\/ws\/call$/, "");
const clipsArg = process.argv.slice(3);

async function replay(clip: string) {
  const ws = new WebSocket(url);
  const transcript: TranscriptEvent[] = [];
  const signals: SignalEvent[] = [];
  let evidence: EvidenceState = EMPTY_EVIDENCE;
  let alert: AlertEvent | null = null;
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`timeout replaying ${clip}`)), 120_000);
    ws.onopen = () => ws.send(JSON.stringify({ type: "replay", clip }));
    ws.onerror = (e) => reject(e);
    ws.onmessage = (m) => {
      const ev = JSON.parse(String(m.data)) as ServerEvent;
      if (ev.type === "transcript") transcript.push(ev);
      if (ev.type === "signal") {
        signals.push(ev);
        evidence = mergeEvidence(evidence, ev, transcript);
      }
      if (ev.type === "alert") alert = ev;
      if (ev.type === "status" && ev.state === "error") reject(new Error(ev.message));
      if (ev.type === "status" && ev.state === "replay_finished") {
        clearTimeout(timer);
        resolve();
      }
    };
  });
  ws.close();
  const tl = buildTimeline(transcript, signals, evidence.items);
  const trig = lineTriggers(signals, evidence.items);
  const a = alert as AlertEvent | null;
  console.log(`\n=== ${clip}: ${transcript.length} lines, ${signals.length} signals, alert=${a?.level ?? "none"} (${a?.signals.join("+") ?? ""})`);
  console.log(`engine=${evidence.engine} model=${evidence.model}`);
  for (const p of evidence.items) console.log(`  [${p.severity}] ${p.name} @utt${p.utterance_id}: "${p.quote}" -> ${p.source}`);
  for (const [id, ts] of trig) console.log(`  line ${id}: ${ts.map((t) => `${t.signal}:${t.label}`).join(", ")}`);
  console.log(`  timeline: duration=${tl.duration}s segments=${tl.segments.length} markers=${tl.markers.length}`);
  const fraudDetails = signals.filter((s) => s.signal === "fraud").at(-1)?.details;
  console.log(`  last fraud details keys: ${fraudDetails ? Object.keys(fraudDetails).join(",") : "-"}`);
  return { clip, transcript, evidence, alert: a, markers: tl.markers.length };
}

const clips: string[] = clipsArg.length
  ? clipsArg
  : ((await (await fetch(`${http}/clips`)).json()) as { name: string }[]).map((c) => c.name);
let failed = false;
for (const c of clips) {
  const r = await replay(c);
  if (!r.transcript.length) { console.error(`FAIL ${c}: no transcript`); failed = true; }
  if (/takeover|grandparent/.test(c) && !r.evidence.items.length) { console.error(`FAIL ${c}: expected fraud evidence`); failed = true; }
  if (/benign/.test(c) && r.alert?.level === "high") { console.error(`FAIL ${c}: benign clip raised high alert`); failed = true; }
}
process.exit(failed ? 1 : 0);
