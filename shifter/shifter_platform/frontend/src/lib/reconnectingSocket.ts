/**
 * Advisory WebSocket with bounded reconnect (#1370, CTF-802).
 *
 * Reconnects with capped exponential backoff and equal jitter: base 1s, capped
 * at 30s, up to 5 attempts. A close code that means "do not retry" stops
 * reconnection: NORMAL (1000), NOT_AUTHENTICATED (4001), and PERMISSION_DENIED
 * (4003) from `shared.enums.WebSocketCloseCode`. A caller can add codes, for
 * example SERVICE_UNAVAILABLE (4503) for a parked shared bus.
 */

const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 30_000;

const NO_RETRY_CLOSE_CODES: ReadonlySet<number> = new Set([1000, 4001, 4003]);

function randomFraction(): number {
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  return buf[0] / 2 ** 32;
}

/** Exponential backoff capped at MAX_DELAY_MS, with equal jitter (half fixed, half random). */
export function retryDelayMs(attempt: number): number {
  const cap = Math.min(BASE_DELAY_MS * 2 ** attempt, MAX_DELAY_MS);
  return Math.round(cap / 2 + randomFraction() * (cap / 2));
}

/** Same-origin `ws:`/`wss:` URL for a socket path. */
export function sameOriginSocketUrl(path: string): string {
  const protocol = globalThis.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${globalThis.location.host}${path}`;
}

export interface ReconnectingSocketHandlers {
  /** Called on each successful open, including after a reconnect. */
  onOpen?: (socket: WebSocket) => void;
  onMessage: (data: string) => void;
  onConnectedChange?: (connected: boolean) => void;
  /** Extra close codes that stop reconnection. */
  terminalCloseCodes?: readonly number[];
}

/** Open `url` and keep it open within the retry budget; returns the cleanup function. */
export function openReconnectingSocket(url: string, handlers: ReconnectingSocketHandlers): () => void {
  const terminal = new Set([...NO_RETRY_CLOSE_CODES, ...(handlers.terminalCloseCodes ?? [])]);
  let cancelled = false;
  let socket: WebSocket | null = null;
  let retryTimeout: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;

  function connect() {
    if (cancelled) return;
    const ws = new WebSocket(url);
    socket = ws;

    ws.onopen = () => {
      if (cancelled) return;
      attempt = 0;
      handlers.onConnectedChange?.(true);
      handlers.onOpen?.(ws);
    };

    ws.onmessage = (event: MessageEvent) => {
      if (cancelled) return;
      handlers.onMessage(event.data as string);
    };

    ws.onclose = (event: CloseEvent) => {
      if (cancelled) return;
      handlers.onConnectedChange?.(false);
      if (terminal.has(event.code) || attempt >= MAX_RECONNECT_ATTEMPTS) {
        return;
      }
      const delay = retryDelayMs(attempt);
      attempt += 1;
      retryTimeout = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // Swallow; `onclose` fires immediately after and drives reconnect/backoff.
    };
  }

  connect();

  return () => {
    cancelled = true;
    if (retryTimeout) clearTimeout(retryTimeout);
    const ws = socket;
    if (ws) {
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      ws.close(1000, "component unmounted");
    }
  };
}
