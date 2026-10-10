// Backend client: config, session creation and the per-session WebSocket, with a mock
// transport that simulates the whole flow when the backend is unreachable.
import type { AppConfig, ClientMsg, ServerMsg, SessionRequest, SessionResponse } from "./contract";
import { MOCK_CONFIG, MockTransport } from "./mock";

const API_BASE: string = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export interface Transport {
  send(msg: ClientMsg): void;
  sendPcm(pcm: ArrayBuffer): void;
  close(): void;
}

export interface TransportHandlers {
  onMsg: (msg: ServerMsg) => void;
  onAudio: (pcm: ArrayBuffer) => void;
  onClose: () => void;
}

// ---------------------------------------------------------------- mode

type ModeSetting = "mock" | "real" | "auto";

function modeSetting(): ModeSetting {
  const q = new URLSearchParams(location.search).get("mock");
  if (q === "1" || q === "true") return "mock";
  if (q === "0" || q === "false") return "real";
  if (import.meta.env.VITE_MOCK === "1") return "mock";
  return "auto";
}

let resolved: Promise<{ mock: boolean; config: AppConfig }> | null = null;

async function fetchJson<T>(path: string, init?: RequestInit, timeoutMs = 2500): Promise<T> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(`${API_BASE}${path}`, { ...init, signal: ctl.signal });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return (await r.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

/** Config + whether we're in mock mode. Auto mode falls back to mock if /api/config fails. */
export function loadConfig(): Promise<{ mock: boolean; config: AppConfig }> {
  if (resolved) return resolved;
  const mode = modeSetting();
  resolved = (async () => {
    if (mode === "mock") return { mock: true, config: MOCK_CONFIG };
    try {
      const config = await fetchJson<AppConfig>("/api/config");
      return { mock: false, config };
    } catch (e) {
      if (mode === "real") throw e;
      return { mock: true, config: MOCK_CONFIG };
    }
  })();
  return resolved;
}

function wsUrl(raw: string): string {
  const base = API_BASE || location.origin;
  const u = new URL(raw, base);
  if (u.protocol === "http:") u.protocol = "ws:";
  if (u.protocol === "https:") u.protocol = "wss:";
  return u.toString();
}

class WsTransport implements Transport {
  private ws: WebSocket;
  private ping: number;
  constructor(url: string, h: TransportHandlers) {
    this.ws = new WebSocket(url);
    this.ws.binaryType = "arraybuffer";
    this.ws.onmessage = (m) => {
      if (typeof m.data === "string") {
        try {
          h.onMsg(JSON.parse(m.data) as ServerMsg);
        } catch {
          /* ignore malformed frames */
        }
      } else {
        h.onAudio(m.data as ArrayBuffer);
      }
    };
    this.ws.onclose = () => {
      clearInterval(this.ping);
      h.onClose();
    };
    this.ping = window.setInterval(() => this.send({ type: "ping" }), 15000);
  }
  send(msg: ClientMsg) {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }
  sendPcm(pcm: ArrayBuffer) {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(pcm);
  }
  close() {
    clearInterval(this.ping);
    this.ws.onclose = null;
    this.ws.onmessage = null;
    if (this.ws.readyState <= WebSocket.OPEN) this.ws.close();
  }
}

/** Create a session and open its socket. */
export async function openSession(req: SessionRequest, h: TransportHandlers): Promise<{ id: string; transport: Transport; mock: boolean }> {
  const { mock } = await loadConfig();
  if (mock) {
    const t = new MockTransport(req, h);
    return { id: t.id, transport: t, mock: true };
  }
  const res = await fetchJson<SessionResponse>(
    "/api/session",
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(req) },
    8000,
  );
  return { id: res.session_id, transport: new WsTransport(wsUrl(res.ws_url || `/ws/session/${res.session_id}`), h), mock: false };
}

export async function fetchReport(id: string): Promise<unknown> {
  return fetchJson<unknown>(`/api/report/${encodeURIComponent(id)}`, undefined, 6000);
}

export function isMockSetting(): boolean {
  return modeSetting() === "mock";
}
