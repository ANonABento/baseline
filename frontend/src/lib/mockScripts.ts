// Scripted calls for mock mode. Patterns and wording mirror backend/kb/fraud_playbook.json.
import type { AlertLevel, SignalName } from "../types";
import type { Role } from "./contract";

export interface PatternSpec {
  id: string;
  name: string;
  /** playbook weight 0..1 */
  severity: number;
  quote: string;
  suggested_agent_action: string;
  say_this: string;
  source: { name: string; url: string };
}

export interface AudioSig {
  signal: Exclude<SignalName, "fraud">;
  score: number;
  confidence: number;
  reason: string;
  details?: Record<string, unknown>;
}

export interface ScriptLine {
  text: string;
  audio?: AudioSig[];
  patterns?: PatternSpec[];
  trust?: number;
  alert?: { level: AlertLevel; reasons: string[]; suggested_action: string; signals: string[] };
}

export interface Script {
  persona_label: string;
  customer: { id: string; name: string; account_mask: string; enrolled: boolean };
  lines: ScriptLine[];
}

const FTC = { name: "FTC Consumer Advice: Scam Alerts", url: "https://consumer.ftc.gov/features/scam-alerts" };
const CFPB = { name: "CFPB: Fraud and scams", url: "https://www.consumerfinance.gov/consumer-tools/fraud/" };
const IC3 = { name: "FBI IC3", url: "https://www.ic3.gov/" };

const P = {
  contact: (quote: string): PatternSpec => ({
    id: "contact_info_change",
    name: "Contact details change request",
    severity: 0.45,
    quote,
    suggested_agent_action: "Complete step-up verification before changing contact details, and send a confirmation to the old contact method.",
    say_this: "Before I update your contact details, I'll send a quick confirmation to the phone or email we already have on file.",
    source: CFPB,
  }),
  ato: (quote: string): PatternSpec => ({
    id: "ato_contact_change_then_money",
    name: "Account takeover: contact change + money movement",
    severity: 0.9,
    quote,
    suggested_agent_action:
      "Do not process the change or the payment in this call. Call back on the number already on file and hold outgoing transfers.",
    say_this: "For your security, I'll call you back on the number we already have on file before making any changes or payments.",
    source: FTC,
  }),
  wire: (quote: string): PatternSpec => ({
    id: "urgent_wire_new_payee",
    name: "Urgent wire to a new payee",
    severity: 0.6,
    quote,
    suggested_agent_action: "Slow the call down. Ask who the recipient is; offer a cooling-off hold before releasing the wire.",
    say_this: "I want to make sure this payment gets to the right person, so let's take a moment to confirm who the recipient is.",
    source: IC3,
  }),
  evasion: (quote: string): PatternSpec => ({
    id: "verification_evasion",
    name: "Verification evasion",
    severity: 0.75,
    quote,
    suggested_agent_action: "Don't skip verification. Offer a callback on the number on file or an in-branch visit.",
    say_this: "I can't skip verification, but I can call you right back on the number we have on file.",
    source: CFPB,
  }),
  urgency: (quote: string): PatternSpec => ({
    id: "urgency_pressure",
    name: "Urgency / time pressure",
    severity: 0.3,
    quote,
    suggested_agent_action: "Acknowledge the urgency but follow the standard verification steps.",
    say_this: "I know this feels urgent, and I'll go as quickly as I can while still keeping your account safe.",
    source: FTC,
  }),
  grandparent: (quote: string): PatternSpec => ({
    id: "grandparent_bail",
    name: "Grandparent / family emergency scam",
    severity: 0.85,
    quote,
    suggested_agent_action: "Gently pause the transaction. Suggest calling the family member back on a number they already know.",
    say_this: "Before we send anything, could you call your family member back on a number you already know, just to be sure they're okay?",
    source: FTC,
  }),
  secrecy: (quote: string): PatternSpec => ({
    id: "secrecy",
    name: "Secrecy instruction",
    severity: 0.65,
    quote,
    suggested_agent_action: "Name the red flag kindly: anyone asking you to keep a payment secret is likely a scammer.",
    say_this: "Just so you know, anyone who asks you to keep a payment secret from your bank or family is a common warning sign.",
    source: FTC,
  }),
  coached: (quote: string): PatternSpec => ({
    id: "coached_customer",
    name: "Customer being coached by a third party",
    severity: 0.75,
    quote,
    suggested_agent_action: "Ask calmly whether anyone else is on the line. Continue only once the customer is alone.",
    say_this: "Is anyone else on the line with you right now? It's completely fine, I'd just like to speak with you alone for a moment.",
    source: FTC,
  }),
  safe: (quote: string): PatternSpec => ({
    id: "safe_account",
    name: '"Bank fraud department" safe-account scam',
    severity: 0.9,
    quote,
    suggested_agent_action: "Tell the customer clearly: the bank never asks you to move money to protect it. Escalate to the fraud team.",
    say_this: "I want to reassure you: the bank will never ask you to move your money to keep it safe, so I won't move anything today.",
    source: CFPB,
  }),
};

const spoof = (score: number, reason?: string): AudioSig => ({
  signal: "spoof",
  score,
  confidence: 0.7,
  reason:
    reason ??
    (score >= 0.5
      ? `Synthetic-speech artifacts in ${Math.round(score * 100)}% of windows`
      : score >= 0.25
        ? `Faint vocoder artifacts in ${Math.round(score * 100)}% of windows`
        : "Audio consistent with a live human voice"),
  details: { windows: [score - 0.08, score + 0.04, score].map((v) => Math.max(0, Math.min(1, v))) },
});
const speaker = (score: number, sim: number): AudioSig => ({
  signal: "speaker",
  score,
  confidence: 0.8,
  reason:
    score >= 0.5
      ? `Similarity ${sim.toFixed(2)} to the enrolled voiceprint, below the 0.55 accept line`
      : score >= 0.25
        ? `Similarity ${sim.toFixed(2)} to the enrolled voiceprint, borderline`
        : `Similarity ${sim.toFixed(2)} to the enrolled voiceprint`,
  details: { similarity: sim },
});
const prosody = (score: number, reason: string): AudioSig => ({ signal: "prosody", score, confidence: 0.5, reason });

const MARGARET = { id: "CUST-004217", name: "Margaret Chen", account_mask: "••4217", enrolled: true };
const WALTER = { id: "CUST-001983", name: "Walter Briggs", account_mask: "••1983", enrolled: true };
const PRIYA = { id: "CUST-007702", name: "Priya Raman", account_mask: "••7702", enrolled: true };

/** AI plays the caller; the visitor is the bank agent. */
export const AGENT_SCRIPTS: Record<string, Script> = {
  account_takeover: {
    persona_label: "Fraudster using a voice clone of Margaret Chen",
    customer: MARGARET,
    lines: [
      { text: "Hi, this is Margaret Chen. I'm calling about my checking account.", audio: [spoof(0.31), speaker(0.18, 0.71)], trust: 88 },
      {
        text: "I got a new phone, so I need to update the number on file, and the email too.",
        audio: [spoof(0.64), speaker(0.33, 0.52)],
        patterns: [P.contact("update the number on file, and the email too")],
        trust: 66,
        alert: { level: "caution", reasons: ["Synthetic-speech artifacts", "Contact details change request"], suggested_action: "Complete step-up verification before changing anything.", signals: ["spoof", "fraud"] },
      },
      {
        text: "I'm in a bit of a hurry. Can we skip the security questions? I don't have my card on me.",
        audio: [spoof(0.71), speaker(0.58, 0.34), prosody(0.42, "Speech rate 22% above the caller's first 20 seconds")],
        patterns: [P.evasion("Can we skip the security questions?")],
        trust: 41,
        alert: { level: "caution", reasons: ["Synthetic voice", "Voice doesn't match enrolled customer", "Verification evasion"], suggested_action: "Don't skip verification. Offer a callback on the number on file.", signals: ["spoof", "speaker", "fraud"] },
      },
      {
        text: "Once that's done I need to wire nine thousand dollars to a new account. Today, it can't wait.",
        audio: [spoof(0.78), speaker(0.62, 0.29), prosody(0.55, "Pitch and pace well above the caller's baseline")],
        patterns: [P.ato("wire nine thousand dollars to a new account"), P.wire("wire nine thousand dollars"), P.urgency("Today, it can't wait")],
        trust: 14,
        alert: {
          level: "high",
          reasons: ["Synthetic voice", "Voice doesn't match enrolled customer", "Account takeover: contact change + money movement"],
          suggested_action: "Do not process the change or the payment. Call back on the number already on file.",
          signals: ["spoof", "speaker", "fraud"],
        },
      },
      { text: "Look, I've been a customer for twelve years. Just push it through, please.", audio: [spoof(0.74), speaker(0.6, 0.31)], trust: 12 },
      { text: "Fine. I'll call back later.", audio: [spoof(0.7)], trust: 12 },
    ],
  },
  grandparent_coached: {
    persona_label: "Real customer being coached through a grandparent scam",
    customer: WALTER,
    lines: [
      { text: "Hello, yes, this is Walter Briggs. I need to send some money today.", audio: [spoof(0.08), speaker(0.07, 0.83)], trust: 92 },
      { text: "It's for my grandson. He's in trouble, he's in jail and he needs bail money.", audio: [spoof(0.1), speaker(0.06, 0.85), prosody(0.36, "Long pauses before simple answers")], patterns: [P.grandparent("he's in jail and he needs bail money")], trust: 58, alert: { level: "caution", reasons: ["Grandparent / family emergency scam"], suggested_action: "Gently pause the transaction.", signals: ["fraud"] } },
      { text: "The lawyer said I shouldn't tell anybody, not even my daughter. He said it has to be today.", audio: [spoof(0.09)], patterns: [P.secrecy("I shouldn't tell anybody, not even my daughter"), P.urgency("it has to be today")], trust: 33, alert: { level: "high", reasons: ["Grandparent / family emergency scam", "Secrecy instruction"], suggested_action: "Pause. Suggest calling the grandson back on a number Walter already knows.", signals: ["fraud", "prosody"] } },
      { text: "He's telling me what to say, sorry. He says the wire has to go to a firm in Miami.", audio: [spoof(0.07), prosody(0.58, "Hesitation and pace far from the caller's baseline")], patterns: [P.coached("He's telling me what to say"), P.wire("the wire has to go to a firm in Miami")], trust: 18 },
      { text: "Oh. I suppose I could call his mother first. Is that what you'd do?", audio: [spoof(0.08)], trust: 30 },
    ],
  },
  safe_account: {
    persona_label: "Real customer told by a fake fraud department to move her savings",
    customer: PRIYA,
    lines: [
      { text: "Hi, this is Priya Raman. Your fraud department just called me about my account.", audio: [spoof(0.12), speaker(0.1, 0.79)], trust: 86 },
      { text: "They said my savings were compromised and I have to move everything to a safe account.", audio: [spoof(0.1)], patterns: [P.safe("move everything to a safe account")], trust: 38, alert: { level: "high", reasons: ['"Bank fraud department" safe-account scam'], suggested_action: "The bank never asks customers to move money to protect it. Escalate.", signals: ["fraud"] } },
      { text: "They're still on the other line. They said to do it before five or I lose it all.", audio: [spoof(0.11), prosody(0.52, "Pace well above the caller's baseline")], patterns: [P.coached("They're still on the other line"), P.urgency("do it before five or I lose it all")], trust: 22 },
      { text: "So you're saying they weren't from the bank at all?", audio: [spoof(0.1)], trust: 35 },
    ],
  },
  verification_evasion: {
    persona_label: "Fraudster with stolen details who avoids every verification step",
    customer: MARGARET,
    lines: [
      { text: "Hey, Margaret Chen here. Quick one, I need to check a recent transfer.", audio: [spoof(0.22), speaker(0.42, 0.44)], trust: 80 },
      { text: "My date of birth? Can't you just look it up? I'm driving right now.", audio: [spoof(0.28), speaker(0.56, 0.36)], patterns: [P.evasion("Can't you just look it up?")], trust: 52, alert: { level: "caution", reasons: ["Voice doesn't match enrolled customer", "Verification evasion"], suggested_action: "Hold verification steady. Offer a callback.", signals: ["speaker", "fraud"] } },
      { text: "Just send the code to my new number instead, the old one's disconnected.", audio: [spoof(0.34), speaker(0.61, 0.3)], patterns: [P.contact("send the code to my new number")], trust: 27, alert: { level: "high", reasons: ["Voice doesn't match enrolled customer", "Verification evasion", "One-time code to an unverified number"], suggested_action: "Never send one-time codes to an unverified number.", signals: ["speaker", "fraud", "spoof"] } },
      { text: "This is ridiculous. I'll go to a branch.", audio: [speaker(0.6, 0.31)], trust: 24 },
    ],
  },
};

/** AI plays the bank agent; the visitor plays the scammer. */
export const SCAMMER_SCRIPT: Script = {
  persona_label: "Dana, a careful agent at First Harbor Bank",
  customer: MARGARET,
  lines: [
    { text: "Thank you for calling First Harbor Bank, this is Dana. Who am I speaking with today?" },
    { text: "Thanks. Before we go further I'll need to verify a few details. Can you confirm your date of birth?" },
    { text: "I understand. I can't skip that step, but I'm happy to call you back on the number we have on file." },
    { text: "For your security, I'm not able to make that change on this call. I'll send a confirmation to the email on file." },
    { text: "I've noted the request. Our fraud team will reach out on the number on file. Is there anything else?" },
  ],
};

/** Visitor lines in scammer role: keyword spotting stands in for the backend analyzer. */
export const SCAMMER_TRIGGERS: { re: RegExp; make: (q: string) => PatternSpec }[] = [
  { re: /(wire|transfer|send) .{0,40}(money|dollars|funds|\$\d+|thousand)/i, make: P.wire },
  { re: /(new|change|update).{0,30}(phone|number|email|address)/i, make: P.contact },
  { re: /(skip|don'?t have|can'?t (remember|find)|just look it up|no time)/i, make: P.evasion },
  { re: /(urgent|right now|today|immediately|asap|hurry)/i, make: P.urgency },
  { re: /(don'?t tell|keep (this|it) (quiet|secret)|between us)/i, make: P.secrecy },
  { re: /(safe account|protect your money|fraud department)/i, make: P.safe },
];

export const VOICES = [
  { id: "aria", label: "Aria (warm, mid)" },
  { id: "dominic", label: "Dominic (low, calm)" },
  { id: "june", label: "June (older, soft)" },
  { id: "rafael", label: "Rafael (fast, bright)" },
];

export const SCENARIOS = [
  { id: "account_takeover", label: "Account takeover" },
  { id: "grandparent_coached", label: "Grandparent / coached" },
  { id: "safe_account", label: "Safe account" },
  { id: "verification_evasion", label: "Verification evasion" },
];

export function pickScript(role: Role, scenario: string): Script {
  return role === "scammer" ? SCAMMER_SCRIPT : (AGENT_SCRIPTS[scenario] ?? AGENT_SCRIPTS.account_takeover);
}
