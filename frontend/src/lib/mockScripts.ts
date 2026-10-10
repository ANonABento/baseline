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
  /** role client: Baseline steps in after this line (reason id from backend/caller/intervention.py) */
  intervene?: string;
}

export interface Script {
  persona_label: string;
  summary?: string;
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

const KEVIN = { id: "CUST-004217", name: "Ethan", account_mask: "••4217", enrolled: true };

const X = {
  gift: (quote: string): PatternSpec => ({
    id: "gift_cards",
    name: "Gift card payment demand",
    severity: 0.8,
    quote,
    suggested_agent_action: "Stop. No real bank, agency or relative in trouble asks to be paid in gift cards.",
    say_this: "No real bank or agency will ever ask you to pay with gift cards.",
    source: FTC,
  }),
  gov: (quote: string): PatternSpec => ({
    id: "government_impersonation",
    name: "Government agency impersonation (IRS / SSA / law enforcement)",
    severity: 0.75,
    quote,
    suggested_agent_action: "The IRS never calls to demand immediate payment or threaten arrest.",
    say_this: "The IRS contacts people by mail, and never demands payment over the phone.",
    source: FTC,
  }),
  remote: (quote: string): PatternSpec => ({
    id: "remote_access",
    name: "Remote-access software / tech support",
    severity: 0.75,
    quote,
    suggested_agent_action: "Never install software or give access to someone who called you.",
    say_this: "Real tech support doesn't call you out of the blue.",
    source: FTC,
  }),
  otp: (quote: string): PatternSpec => ({
    id: "otp_redirect",
    name: "One-time code redirection",
    severity: 0.55,
    quote,
    suggested_agent_action: "Never read a one-time code to anyone who calls you.",
    say_this: "Your bank will never ask you to read back a one-time code.",
    source: CFPB,
  }),
};

/** Role client: the AI fraudster calls the visitor. Lines are the caller's; Baseline analyzes them. */
export const CLIENT_SCRIPTS: Record<string, Script> = {
  grandchild: {
    persona_label: "A scammer using a cloned voice of Ethan",
    summary: "A scammer used a cloned voice of Ethan to say he'd been arrested, then asked his grandparent for bail money in gift cards and told them not to tell his mom.",
    customer: KEVIN,
    lines: [
      { text: "Grandma? It's me, Ethan. I'm in really big trouble, please don't hang up.", audio: [spoof(0.38), speaker(0.16, 0.71)], trust: 82 },
      {
        text: "I was in an accident and they arrested me. I need three thousand dollars for bail today.",
        audio: [spoof(0.66), speaker(0.22, 0.64), prosody(0.44, "Pace 25% above the caller's first lines")],
        patterns: [P.grandparent("they arrested me. I need three thousand dollars for bail")],
        trust: 52,
        alert: { level: "caution", reasons: ["Grandparent / family emergency scam", "Synthetic-speech artifacts"], suggested_action: "Hang up and call Ethan back on his usual number.", signals: ["fraud", "spoof"] },
        intervene: "voice_clone",
      },
      {
        text: "The lawyer says gift cards are fastest. Can you go to the store? And please don't tell Mom.",
        audio: [spoof(0.78)],
        patterns: [X.gift("gift cards are fastest"), P.secrecy("please don't tell Mom")],
        trust: 16,
        alert: { level: "high", reasons: ["Synthetic voice likely", "Gift card payment demand", "Secrecy instruction"], suggested_action: "Hang up. Call Ethan back on his usual number.", signals: ["fraud", "spoof"] },
        intervene: "gift_cards",
      },
      { text: "Grandma, please, just read me the numbers on the back of the cards when you have them.", audio: [spoof(0.74)], trust: 14 },
      { text: "Okay. I have to go, they're taking the phone.", audio: [spoof(0.7)], trust: 14 },
    ],
  },
  fake_bank: {
    persona_label: "A fraudster posing as First City's fraud department",
    summary: "A fraudster posing as First City's fraud department invented a suspicious charge to get Ethan's one-time code.",
    customer: KEVIN,
    lines: [
      { text: "Hi, is this Ethan? This is Alex from the First City fraud department. We just flagged a suspicious charge on your card.", audio: [spoof(0.31)], trust: 86 },
      {
        text: "To cancel it I need to verify you. We just texted you a six-digit code. Can you read it to me?",
        audio: [spoof(0.58)],
        patterns: [X.otp("Can you read it to me?")],
        trust: 48,
        alert: { level: "caution", reasons: ["One-time code redirection"], suggested_action: "Never read a one-time code to a caller.", signals: ["fraud"] },
        intervene: "secret_request",
      },
      {
        text: "Your account is still exposed, so we'll move your savings to a secure holding account right now.",
        audio: [spoof(0.71)],
        patterns: [P.safe("move your savings to a secure holding account")],
        trust: 15,
        alert: { level: "high", reasons: ['"Bank fraud department" safe-account scam', "Synthetic voice likely"], suggested_action: "Hang up and call the number on your card.", signals: ["fraud", "spoof"] },
        intervene: "safe_account",
      },
      { text: "Please don't hang up, the case closes if we disconnect.", audio: [spoof(0.7)], trust: 14 },
    ],
  },
  irs: {
    persona_label: "A fraudster posing as an IRS officer",
    summary: "A fraudster posing as an IRS officer threatened arrest over 'back taxes' and demanded gift cards.",
    customer: KEVIN,
    lines: [
      { text: "This is Officer Daniel Ross with the IRS. Am I speaking with Ethan? There's a warrant pending in your name.", audio: [spoof(0.4)], patterns: [X.gov("Officer Daniel Ross with the IRS")], trust: 55, alert: { level: "caution", reasons: ["Government agency impersonation"], suggested_action: "The IRS never calls to demand payment.", signals: ["fraud"] }, intervene: "government" },
      { text: "You owe four thousand eight hundred dollars. For immediate settlement we accept gift cards.", audio: [spoof(0.72)], patterns: [X.gift("we accept gift cards")], trust: 15, alert: { level: "high", reasons: ["Gift card payment demand", "Synthetic voice likely"], suggested_action: "Hang up.", signals: ["fraud", "spoof"] }, intervene: "gift_cards" },
      { text: "Which store is closest to you? Stay on the line while you drive there.", audio: [spoof(0.7)], trust: 14 },
    ],
  },
  tech_support: {
    persona_label: "A fraudster posing as Windows tech support",
    summary: "A fraudster posing as tech support pushed remote-access software, then faked a refund overpayment.",
    customer: KEVIN,
    lines: [
      { text: "Hello, is this Ethan? This is Mark from Windows support. Your computer has been sending us virus alerts.", audio: [spoof(0.3)], trust: 80 },
      { text: "I need you to install AnyDesk so I can fix it remotely. Read me the access code on the screen.", audio: [spoof(0.62)], patterns: [X.remote("install AnyDesk so I can fix it remotely")], trust: 40, alert: { level: "caution", reasons: ["Remote-access software / tech support"], suggested_action: "Never let a caller into your computer.", signals: ["fraud"] }, intervene: "remote_access" },
      { text: "I refunded twenty-five hundred instead of two fifty by mistake. Please send the difference back today.", audio: [spoof(0.74)], patterns: [X.remote("send the difference back today")], trust: 15, alert: { level: "high", reasons: ["Overpayment / refund scam", "Synthetic voice likely"], suggested_action: "Hang up.", signals: ["fraud", "spoof"] }, intervene: "generic" },
    ],
  },
};

/** What Baseline says (mirrors backend/caller/intervention.py). */
export const MOCK_MESSAGES: Record<string, string> = {
  secret_request: "This looks like a scam. First City will never ask for your one-time code.",
  card_request: "This looks like a scam. Never read card numbers or PINs to a caller.",
  gift_cards: "This looks like a scam. No real bank or agency asks for gift cards.",
  voice_clone: "This voice may not really be Ethan. Hang up and call him back.",
  safe_account: "This looks like a scam. First City never asks you to move money to a safe account.",
  remote_access: "This looks like a scam. Never let a caller into your computer.",
  government: "This looks like a scam. The IRS never calls to demand payment.",
  generic: "This call looks like a scam. Hang up and call the number on your card.",
};
export const MOCK_INTRO = "This is Baseline, from First City.";

/** Visitor lines in client role: a mini client_risk (backend/detectors/client_risk.py). */
export const CLIENT_TRIGGERS: { re: RegExp; reason: string; reason_id: string; secret: boolean }[] = [
  { re: /\b(code|passcode)\s+(is|says)\b/i, reason: "About to read out a one-time code", reason_id: "share_code", secret: true },
  { re: /(\d[\s-]?){4,}|\b(zero|one|two|three|four|five|six|seven|eight|nine)\b(\W+\b(zero|one|two|three|four|five|six|seven|eight|nine)\b){3,}/i, reason: "Reading out digits the caller asked for", reason_id: "reading_digits", secret: true },
  { re: /\b(let me|i'?ll)\s+(get|grab|find)\s+(my|the)\s+(card|wallet)/i, reason: "Getting their card for the caller", reason_id: "get_card", secret: true },
  { re: /\b(card number|pin|social security)\s+(is|number is)\b/i, reason: "About to read out a card number", reason_id: "share_card", secret: true },
  { re: /\b(which|what)\s+store\b|\b(buy|get)\s+(the\s+)?gift\s*cards?\b/i, reason: "Agreeing to pay with gift cards", reason_id: "gift_cards", secret: false },
  { re: /\bi\s+won'?t\s+tell\b|\bi\s+promise\b/i, reason: "Promising to keep it secret", reason_id: "secrecy_promise", secret: false },
  { re: /\b(i'?ll|i will|let me)\s+(go to|send|transfer|wire|install|download)\b|\bhow much\b/i, reason: "Going along with the caller", reason_id: "send_money", secret: false },
];

/** AI plays the bank agent; the visitor plays the scammer. */
export const SCAMMER_SCRIPT: Script = {
  persona_label: "Jordan, a careful agent at First City Bank",
  customer: KEVIN,
  lines: [
    { text: "Thank you for calling First City Bank, this is Jordan. Who am I speaking with today?" },
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

export const SCENARIOS: { id: string; label: string; role: "client" | "scammer"; brief: string }[] = [
  { id: "grandchild", label: "Ethan in trouble (voice clone)", role: "client", brief: "You're Ethan's grandparent. 'Ethan' calls in a panic." },
  { id: "fake_bank", label: "First City 'fraud department'", role: "client", brief: "Someone from 'First City fraud' calls about a suspicious charge." },
  { id: "irs", label: "IRS back taxes", role: "client", brief: "An 'IRS officer' says you owe back taxes." },
  { id: "tech_support", label: "Tech support refund", role: "client", brief: "'Tech support' found a virus on your computer." },
  { id: "account_takeover", label: "Account takeover", role: "scammer", brief: "Change the phone number on file, then wire $9,000 out." },
  { id: "verification_evasion", label: "Verification evasion", role: "scammer", brief: "Reset online banking without passing the security questions." },
  { id: "safe_account", label: "'Safe account' transfer", role: "scammer", brief: "Move the savings to a 'secure holding account'." },
];

export function pickScript(role: Role, scenario: string): Script {
  return role === "scammer" ? SCAMMER_SCRIPT : (CLIENT_SCRIPTS[scenario] ?? CLIENT_SCRIPTS.grandchild);
}
