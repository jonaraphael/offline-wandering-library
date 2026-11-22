import allowlist from "./allowlist.json" with {type: "json"};

const MAX_ARCHIVE_RANGE = 64 * 2 ** 20;

function requestedRange(header, size, bounded) {
  if (!header) return bounded ? null : {size};
  const match = /^bytes=(\d+)-(\d*)$/.exec(header);
  if (!match) return null;
  const start = Number(match[1]);
  const requestedEnd = match[2] ? Number(match[2]) : size - 1;
  if (!Number.isSafeInteger(requestedEnd) || (bounded && (!match[2] || requestedEnd >= size))) return null;
  const end = Math.min(requestedEnd, size - 1);
  if (!Number.isSafeInteger(start) || start > end) return null;
  return {size: end - start + 1, expected: "bytes " + start + "-" + end + "/" + size};
}

export function relay(allowed, fetchUpstream = fetch) {
  return {async fetch(request, env) {
    const origin = request.headers.get("Origin");
    const headers = new Headers({"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
      "Vary": "Origin"});
    const reply = (status, text) => new Response(request.method === "HEAD" ? null : text, {status, headers});
    if (!env.ALLOWED_ORIGIN || origin !== env.ALLOWED_ORIGIN) return reply(403, "Origin denied");
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges");
    const url = new URL(request.url);
    const id = /^\/assets\/([a-z0-9_-]+)$/.exec(url.pathname)?.[1];
    if (url.search || !Object.hasOwn(allowed, id)) return reply(404, "Unknown asset");
    if (request.method === "OPTIONS") {
      headers.set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
      headers.set("Access-Control-Allow-Headers", "Range");
      return reply(204, null);
    }
    if (!["GET", "HEAD"].includes(request.method)) return reply(405, "Method denied");
    const ip = request.headers.get("CF-Connecting-IP");
    if (!ip || !env.REQUEST_LIMIT) return reply(503, "Relay unavailable");
    if (!(await env.REQUEST_LIMIT.limit({key: ip})).success) {
      headers.set("Retry-After", "60");
      return reply(429, "Try again later");
    }
    const {url: upstreamUrl, bytes, max_range_bytes: maxRange} = allowed[id];
    const range = request.headers.get("Range");
    const span = requestedRange(range, bytes, Boolean(maxRange));
    if (!span || (maxRange && span.size > Math.min(maxRange, MAX_ARCHIVE_RANGE))) {
      headers.set("Content-Range", "bytes */" + bytes);
      return reply(416, "Range unavailable");
    }
    const upstreamHeaders = new Headers({"Accept-Encoding": "identity"});
    if (range) upstreamHeaders.set("Range", range);
    let upstream;
    try {
      upstream = await fetchUpstream(upstreamUrl, {method: request.method, headers: upstreamHeaders,
        redirect: "manual", cache: "no-store", signal: request.signal});
    } catch {
      // A connection failure is transient; 503 tells the builder to retry or
      // rotate to another route instead of treating the route as wrong.
      return reply(503, "Publisher unavailable");
    }
    if (upstream.status === 429 || upstream.status === 503) {
      await upstream.body?.cancel();
      const retry = upstream.headers.get("Retry-After");
      if (retry && /^\d{1,4}$/.test(retry)) headers.set("Retry-After", retry);
      return reply(upstream.status, "Publisher is busy");
    }
    const length = upstream.headers.get("Content-Length");
    const encoding = upstream.headers.get("Content-Encoding");
    if (upstream.status !== (range ? 206 : 200) ||
        (length !== null && Number(length) !== span.size) || (encoding && encoding !== "identity") ||
        (range && upstream.headers.get("Content-Range") !== span.expected)) {
      await upstream.body?.cancel();
      return reply(502, "Publisher response did not match the catalog");
    }
    headers.set("Content-Type", "application/octet-stream");
    for (const name of ["Content-Length", "Content-Range", "Accept-Ranges"]) {
      if (upstream.headers.has(name)) headers.set(name, upstream.headers.get(name));
    }
    // Pass the publisher body straight through so the runtime streams it
    // without running JavaScript per chunk. A byte-counting TransformStream
    // here used the free plan's per-request CPU allowance under parallel load,
    // and Cloudflare cut 36/36 parallel 4 MiB responses short (0.4-2.9 MB).
    // The declared length lets clients detect a short body; the builder also
    // checks every byte count and publisher SHA-1 itself.
    headers.set("Content-Length", String(span.size));
    return new Response(request.method === "HEAD" ? null : upstream.body, {status: upstream.status, headers});
  }};
}

export default relay(allowlist);
