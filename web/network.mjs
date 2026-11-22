const NETWORK_IDLE_MS = 60_000;
const PROBE_TIMEOUT_MS = 5_000;

export class SourceError extends Error {
  constructor(message, {whole = false, connection = false, status} = {}) {
    super(message);
    this.whole = whole;
    this.connection = connection;
    this.status = status;
  }
}

function retryAfter(response) {
  const value = response.headers.get("Retry-After")?.trim();
  if (!value) return;
  if (/^\d+$/.test(value)) return Math.min(Number(value) * 1000, 2 ** 31 - 1);
  const date = Date.parse(value);
  if (Number.isFinite(date)) return Math.min(Math.max(0, date - Date.now()), 2 ** 31 - 1);
}

// Use route cooldowns so one throttled source never holds up a usable mirror.
export function routeCooldowns(network) {
  const until = new Map();
  const waiting = route => Math.max(0, (until.get(route) || 0) - Date.now());
  return {
    waiting,
    defer(route, ms) {
      if (ms > 0) until.set(route, Math.max(until.get(route) || 0, Date.now() + ms));
    },
    async delay(routes, minimum) {
      const retry = Math.min(...routes.map(waiting).filter(Boolean));
      await network.delay(Math.max(minimum || 0, Number.isFinite(retry) ? retry : 0) || minimum);
    }
  };
}

export function createNetwork({fetchFile = globalThis.fetch, signal, probeURL, onWaiting = () => {}, onRestored = () => {},
    events = globalThis, online = () => globalThis.navigator?.onLine !== false, retryMs = 1_000} = {}) {
  function delay(ms, wakeOnline = false) {
    signal?.throwIfAborted();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(wake, ms);
      function finish() {
        clearTimeout(timer);
        signal?.removeEventListener("abort", abort);
        if (wakeOnline) events.removeEventListener?.("online", wake);
      }
      function wake() { finish(); resolve(); }
      function abort() { finish(); reject(signal.reason); }
      signal?.addEventListener("abort", abort, {once: true});
      if (wakeOnline) events.addEventListener?.("online", wake, {once: true});
    });
  }

  async function reachable(url = probeURL, {external = false} = {}) {
    if (!online()) return false;
    if (!url) return true;
    try {
      const timeout = AbortSignal.timeout(PROBE_TIMEOUT_MS);
      const response = await fetchFile(url, {cache: "no-store", method: "HEAD",
        ...(external ? {mode: "no-cors", credentials: "omit", referrerPolicy: "no-referrer"} : {}),
        signal: signal ? AbortSignal.any([signal, timeout]) : timeout});
      // A real HTTP response, even a 404 or 503, establishes connectivity.
      return external || response.type !== "opaque";
    } catch (_) {
      signal?.throwIfAborted();
      return false;
    }
  }

  async function waitForConnection() {
    let backoff = retryMs, waited = false;
    while (!await reachable()) {
      waited = true;
      onWaiting();
      await delay(backoff, true);
      backoff = Math.min(backoff * 2, 60_000);
    }
    if (waited) onRestored();
    return waited;
  }

  async function retry(operation) {
    for (let attempt = 0;;) {
      signal?.throwIfAborted();
      try { return await operation(); }
      catch (error) {
        signal?.throwIfAborted();
        if (!(error instanceof SourceError)) throw error;
        if ((error.connection || !online()) && await waitForConnection()) continue;
        if (attempt++) throw error;
        await delay(Math.max(retryMs, error.retryAfterMs || 0));
      }
    }
  }

  return {reachable, waitForConnection, retry, delay: (ms = retryMs) => delay(ms), offline: () => !online()};
}

export async function receiveFile(url, {fetchFile, signal, headers = {}, check, onChunk}) {
  const controller = new AbortController();
  const requestSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
  async function receive(operation, beforeResponse = false) {
    const timer = setTimeout(() => controller.abort(), NETWORK_IDLE_MS);
    try { return await operation(); }
    catch (_) {
      signal?.throwIfAborted();
      const error = new SourceError(controller.signal.aborted ? "Source stopped sending data" :
        "Connection or browser access failed", {connection: true});
      error.beforeResponse = beforeResponse;
      throw error;
    } finally { clearTimeout(timer); }
  }
  const response = await receive(() => fetchFile(url, {
    headers, signal: requestSignal, cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer"
  }), true);
  const reader = response.body?.getReader();
  try {
    check(response);
    if (!reader) throw new SourceError("Source returned no data (HTTP " + response.status + ")", {status: response.status});
    for (;;) {
      signal?.throwIfAborted();
      const packet = await receive(() => reader.read());
      if (packet.done) break;
      await onChunk(packet.value);
    }
  } catch (error) {
    if (error instanceof SourceError) error.retryAfterMs = retryAfter(response);
    throw error;
  } finally {
    void reader?.cancel().catch(() => {});
    reader?.releaseLock();
  }
}
