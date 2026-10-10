import type { Customer } from "../types";
import { Panel } from "./Panel";

export function CustomerPanel({ customer }: { customer: Customer | null }) {
  const c = customer ?? {
    id: "CUST-004217", name: "Margaret Chen", enrolled: true, voiceprint: "stub (not enrolled yet)",
    phone_on_file: "(650) 555-0142", member_since: "2009", segment: "Retail / senior",
  };
  const rows: [string, string][] = [
    ["Customer ID", c.id],
    ["Phone on file", c.phone_on_file],
    ["Member since", c.member_since],
    ["Segment", c.segment],
    ["Voiceprint", c.voiceprint],
  ];
  return (
    <Panel title="Customer on file">
      <div className="mb-4 flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-full bg-indigo-500/20 text-lg font-semibold text-indigo-300">
          {c.name.split(" ").map((p) => p[0]).join("")}
        </div>
        <div>
          <div className="font-semibold text-slate-100">{c.name}</div>
          <div className="text-xs text-emerald-400">{c.enrolled ? "● Voice baseline enrolled" : "○ Not enrolled"}</div>
        </div>
      </div>
      <dl className="space-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2">
            <dt className="text-slate-500">{k}</dt>
            <dd className="text-right font-mono text-xs leading-5 text-slate-300">{v}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}
