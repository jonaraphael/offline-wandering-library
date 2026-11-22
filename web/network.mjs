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

export function createNetwork({fetchFile = globalThis.fetch, signal, probeURL, onWaiting = () => {},
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

  async function reachable() {
    if (!online()) return false;
    if (!probeURL) return true;
    try {
      const timeout = AbortSignal.timeout(PROBE_TIMEOUT_MS);
      const response = await fetchFile(probeURL, {cache: "no-store", method: "HEAD",
        signal: signal ? AbortSignal.any([signal, timeout]) : timeout});
      // A real HTTP response, even a 404 or 503, establishes connectivity.
      return response.type !== "opaque";
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
        await delay(retryMs);
      }
    }
  }

  return {waitForConnection, retry, delay: (ms = retryMs) => delay(ms), offline: () => !online()};
}

export async function receiveFile(url, {fetchFile, signal, headers = {}, check, onChunk}) {
  const controller = new AbortController();
  const requestSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
  async function receive(operation) {
    const timer = setTimeout(() => controller.abort(), NETWORK_IDLE_MS);
    try { return await operation(); }
    catch (_) {
      signal?.throwIfAborted();
      throw new SourceError(controller.signal.aborted ? "Source stopped sending data" :
        "Connection or browser access failed", {connection: true});
    } finally { clearTimeout(timer); }
  }
  const response = await receive(() => fetchFile(url, {
    headers, signal: requestSignal, cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer"
  }));
  if (!response.body) throw new SourceError("Source returned no data (HTTP " + response.status + ")", {status: response.status});
  const reader = response.body.getReader();
  try {
    check(response);
    for (;;) {
      signal?.throwIfAborted();
      const packet = await receive(() => reader.read());
      if (packet.done) break;
      await onChunk(packet.value);
    }
  } finally {
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
