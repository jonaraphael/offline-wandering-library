const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;
const PROBE_INTERVAL = 15 * MINUTE;
const PROBE_TIMEOUT = 5_000;
const FAILED_FILES = 3;

export const RELAY_WAIT_REASON = "waiting for the download relay";
export const RELAY_WAIT_MESSAGE = "The download relay isn’t answering. It may have reached today’s free limit, " +
  "which resets at midnight UTC. Sync keeps trying by itself every 15 minutes.";
export const isSmallRelayRoute = (url, id) => new URL(url).pathname === "/assets/" + id;

export function nextRelayProbe(now) {
  let resetProbe = Math.floor(now / DAY) * DAY + 5 * MINUTE;
  if (resetProbe <= now) resetProbe += DAY;
  return Math.min(now + PROBE_INTERVAL, resetProbe);
}

export function createRelayWait({routes, archives = {}, assets, fetchFile, network, signal}) {
  const smallRoutes = Object.entries(routes).flatMap(([id, urls]) => urls.filter(url => isSmallRelayRoute(url, id)));
  const relayOrigins = new Set([...smallRoutes, ...Object.values(archives).flat()].map(url => new URL(url).origin));
  const isRelay = url => relayOrigins.has(new URL(url, globalThis.location?.href || "https://owl.invalid/").origin);
  let probeURL;
  let probeSize = Infinity;
  for (const asset of assets) {
    const url = routes[asset.id]?.find(route => isSmallRelayRoute(route, asset.id));
    if (url && asset.format !== "zim" && asset.size_bytes < probeSize) {
      probeURL = url;
      probeSize = asset.size_bytes;
    }
  }
  const offlineEvidence = new Set();
  let unavailable = false, lastProbe, provenHost;
  const directHosts = new Map();
  const pageOrigin = globalThis.location?.origin;
  for (const url of relayOrigins.size ? Object.values(routes).flat() : []) {
    const origin = new URL(url).origin;
    if (origin !== pageOrigin && !isRelay(url) && !directHosts.has(origin)) directHosts.set(origin, url);
  }
  const directProbes = [...directHosts.values()];

  function answered() {
    offlineEvidence.clear();
  }

  async function observeFailure(id) {
    if (!probeURL || !directProbes.length) return false;
    if (offlineEvidence.has(id)) return true;
    if (!await network.reachable() || !await otherHostReachable()) {
      answered();
      return false;
    }
    offlineEvidence.add(id);
    if (offlineEvidence.size >= FAILED_FILES) unavailable = true;
    return true;
  }

  async function otherHostReachable() {
    const probeHost = url => network.reachable(url, {external: true});
    if (provenHost && await probeHost(provenHost)) return true;
    const remaining = directProbes.filter(url => url !== provenHost);
    for (let offset = 0; offset < remaining.length; offset += FAILED_FILES) {
      const batch = remaining.slice(offset, offset + FAILED_FILES);
      const settled = await Promise.all(batch.map(probeHost));
      provenHost = batch[settled.indexOf(true)];
      if (provenHost) return true;
    }
    return false;
  }

  async function probe() {
    lastProbe = Date.now();
    try {
      const timeout = AbortSignal.timeout(PROBE_TIMEOUT);
      const response = await fetchFile(probeURL, {method: "HEAD",
        cache: "no-store", mode: "cors", credentials: "omit", redirect: "error", referrerPolicy: "no-referrer",
        signal: signal ? AbortSignal.any([signal, timeout]) : timeout});
      void response.body?.cancel().catch(() => {});
      // Any readable HTTP reply establishes that the Worker can answer.
      if (!response.status) return;
      unavailable = false;
      answered();
    } catch (_) {
      signal?.throwIfAborted();
    }
  }

  async function resume() {
    if (!probeURL) return;
    unavailable = true;
    await network.waitForConnection();
    await probe();
  }

  async function wait(onWaiting) {
    while (unavailable) {
      const now = Date.now();
      const wake = new AbortController();
      const waiting = {kind: "waiting-relay", tryNow: () => wake.abort()};
      onWaiting(waiting);
      await network.delay(Math.max(0, nextRelayProbe(lastProbe ?? now) - now), wake.signal);
      if (await network.waitForConnection()) onWaiting(waiting);
      await probe();
    }
  }

  return {isRelay, observeFailure, answered, resume, wait,
    get unavailable() { return unavailable; }};
}
