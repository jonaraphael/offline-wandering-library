import {receiveFile, SourceError} from "./network.mjs";

const MiB = 2 ** 20;
const WINDOW_PIECES = 16;
const MIN_LANES = 1;
const MAX_LANES = 8;

export async function streamRequest(url, range, expected, fetchFile, signal, onChunk) {
  let count = 0;
  await receiveFile(url, {
    fetchFile, signal, headers: range ? {Range: "bytes=" + range.start + "-" + range.end} : {},
    check(response) {
      if (range ? response.status !== 206 ||
          response.headers.get("Content-Range") !== "bytes " + range.start + "-" + range.end + "/" + range.total :
          response.status !== 200) {
        throw new SourceError(range && response.ok ? "Source did not return the pinned byte range" : "HTTP " + response.status,
          {status: response.status});
      }
    },
    async onChunk(chunk) {
      count += chunk.byteLength;
      if (count > expected) throw new SourceError("Source exceeded the pinned byte count");
      await onChunk(chunk);
    }
  });
  if (count !== expected) throw new SourceError("Source ended before the pinned byte count", {connection: true});
}

export function publisherPin(published, asset) {
  const record = published?.archives?.[asset.id];
  if (!record) return null;
  const size = published.piece_bytes;
  const digests = atob(record.sha1);
  if (record.sha256 !== asset.sha256 || size !== 4 * MiB ||
      digests.length !== Math.ceil(asset.size_bytes / size) * 20) {
    throw Error("Publisher piece manifest does not match " + asset.title);
  }
  return {
    size,
    async matches(index, bytes) {
      const digest = new Uint8Array(await globalThis.crypto.subtle.digest("SHA-1", bytes));
      return digest.every((byte, i) => byte === digests.charCodeAt(index * 20 + i));
    }
  };
}

export function checkAlignment(pin, asset, part) {
  if (part.start % pin.size || (part.start + part.bytes !== asset.size_bytes && part.bytes % pin.size)) {
    throw Error("Publisher pieces do not align with the saved parts of " + asset.title);
  }
}

export function archiveSession(asset, pin, {direct, relay = [], fetchFile, signal, network}) {
  let lanes = 6, previousRate = 0, growth = true, sampled = false, preferred = direct[0];
  const relayURLs = new Set(relay);
  // Relay routes ordered by sampled speed. A route that returns wrong or
  // unusable data is dropped; a throttled or dropped request moves the next
  // pieces to another relay route. The slow default mirror is the last resort
  // for a piece, so one relay hiccup no longer costs a 4 MiB piece at 0.46 MB/s.
  let ranked = [...relay];
  const dropped = new Set();
  const liveRelays = () => ranked.filter(url => !dropped.has(url));
  const routes = () => [...new Set([...(dropped.has(preferred) ? [] : [preferred]), ...liveRelays(), ...direct])];
  function rotate(url) {
    const relays = liveRelays();
    if (!relays.length) return direct[0];
    const next = relays[(relays.indexOf(url) + 1) % relays.length];
    return next === undefined ? relays[0] : next;
  }

  async function read(url, index, length, requestSignal) {
    const start = index * pin.size;
    const range = {start, end: start + length - 1, total: asset.size_bytes};
    const bytes = new Uint8Array(length);
    let cursor = 0;
    await streamRequest(url, range, length, fetchFile, requestSignal, chunk => {
      bytes.set(chunk, cursor);
      cursor += chunk.byteLength;
    });
    if (!await pin.matches(index, bytes)) throw new SourceError("Publisher piece SHA-1 mismatch");
    return bytes;
  }

  async function select(index, length, requestSignal, accept) {
    sampled = true;
    const measure = async url => {
      const start = performance.now();
      // A nonresponsive optional peer must not block the default route.
      const probeSignal = relayURLs.has(url) ?
        AbortSignal.any([requestSignal, AbortSignal.timeout(20_000)]) : requestSignal;
      try {
        const bytes = await read(url, index, length, probeSignal);
        return {url, bytes, elapsed: performance.now() - start};
      } catch (error) {
        requestSignal.throwIfAborted();
        if (!(error instanceof SourceError) && !probeSignal.aborted) throw error;
        return null;
      }
    };
    const [baseline, ...peers] = await Promise.all([preferred, ...relay].map(measure));
    const answered = peers.filter(Boolean).sort((a, b) => a.elapsed - b.elapsed);
    ranked = [...answered.map(peer => peer.url), ...relay.filter(url => !answered.some(peer => peer.url === url))];
    const fastest = answered[0];
    if (fastest && (!baseline || fastest.elapsed * 1.25 < baseline.elapsed)) preferred = fastest.url;
    const sample = baseline || fastest;
    if (sample) await accept(index, sample.bytes);
  }

  return async function transfer(part, {restore, accept, ordered}) {
    const first = part.start / pin.size;
    const limit = first + Math.ceil(part.bytes / pin.size);
    const controller = new AbortController();
    const requestSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
    try {
      for (let start = first; start < limit; start += WINDOW_PIECES) {
        requestSignal.throwIfAborted();
        const end = Math.min(start + WINDOW_PIECES, limit);
        const window = new Array(end - start);
        let committed = start, written = Promise.resolve(), transferred = 0, backoff = false;
        const began = performance.now();
        const lengthOf = index => Math.min(pin.size, asset.size_bytes - index * pin.size);
        // Serialize positioned writes and advance SHA-256 over the contiguous prefix.
        function write(index, bytes, persist) {
          written = written.then(async () => {
            requestSignal.throwIfAborted();
            await accept(index, bytes, persist);
            window[index - start] = bytes;
            while (window[committed - start]) {
              ordered(window[committed - start]);
              window[committed - start] = null;
              committed++;
            }
          });
          return written;
        }

        if (relay.length && !sampled && lengthOf(start) === pin.size) {
          const saved = await restore(start, lengthOf(start));
          if (saved) await write(start, saved, false);
          else await select(start, lengthOf(start), requestSignal, (index, bytes) => write(index, bytes, true));
        }
        let remaining = Array.from({length: end - committed}, (_, i) => committed + i);
        let attempt = 0;
        while (remaining.length) {
          let cursor = 0, fatal, throttled = false;
          const failed = [];
          async function lane() {
            while (!throttled && cursor < remaining.length) {
              requestSignal.throwIfAborted();
              const index = remaining[cursor++];
              const length = lengthOf(index);
              const saved = await restore(index, length);
              if (saved) {
                await write(index, saved, false);
                continue;
              }
              let failure, bytes;
              for (const url of routes()) {
                try {
                  bytes = await read(url, index, length, requestSignal);
                  break;
                } catch (error) {
                  requestSignal.throwIfAborted();
                  if (!(error instanceof SourceError)) throw error;
                  failure = error;
                  backoff = true;
                  // Throttled (429/503) or dropped relay requests rotate to the
                  // next relay route; only a wrong or unusable response drops a
                  // route. Falling back to the 0.46 MB/s mirror on the first relay
                  // error made a real build crawl seconds after starting.
                  if (relayURLs.has(url)) {
                    if (!(error.status === 429 || error.status === 503 || error.connection)) dropped.add(url);
                    if (preferred === url) preferred = rotate(url);
                  }
                }
              }
              if (bytes) {
                transferred += length;
                await write(index, bytes, true);
              } else {
                failed.push({index, error: failure});
                throttled ||= failure.status === 429 || failure.status === 503;
              }
            }
          }
          const jobs = Array.from({length: Math.min(lanes, remaining.length)}, async () => {
            try { await lane(); }
            catch (error) {
              fatal ??= error;
              controller.abort();
            }
          });
          await Promise.all(jobs);
          if (fatal) throw fatal;
          if (!failed.length) break;
          remaining = [...failed.map(({index}) => index), ...remaining.slice(cursor)];
          lanes = Math.max(MIN_LANES, Math.floor(lanes / 2));
          if ((failed.some(({error}) => error.connection) || network.offline()) &&
              await network.waitForConnection()) continue;
          if (++attempt >= 3) throw failed[0].error;
          await network.delay(throttled ? 1_000 * 2 ** attempt : undefined);
        }
        if (backoff) {
          if (!attempt) lanes = Math.max(MIN_LANES, Math.floor(lanes / 2));
          previousRate = 0;
          growth = true;
        } else if (transferred >= lanes * pin.size) {
          const rate = transferred / (performance.now() - began);
          if (growth && (!previousRate || rate > previousRate * 1.03)) lanes = Math.min(MAX_LANES, lanes + 1);
          else if (growth) {
            lanes = Math.max(MIN_LANES, lanes - 1);
            growth = false;
          }
          previousRate = rate;
        }
      }
    } finally {
      controller.abort();
    }
  };
}
