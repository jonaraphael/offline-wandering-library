import {receiveFile, routeCooldowns, SourceError} from "./network.mjs";
import {diag, routeLabel} from "./diagnostics.mjs";

const MiB = 2 ** 20;
// 16 pieces (64 MiB) per window. A window's writes drain while the next window
// downloads (at most two windows in memory), so throughput approaches the
// slower of network and drive instead of their sum.
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

// relayReady() is false while the relay looks unavailable (often its free
// daily limit). Pieces then use the direct mirror, refreshRelay() rechecks the
// relay on its own schedule, and the session samples again once it answers.
// onRoute({fast}) reports whether the relay or the fastest route is in use.
// Once drain aborts, no new piece starts; after the pieces in flight are
// journaled, atSavePoint() waits there for the pause. onInflight() reports
// arriving bytes at most every 250 ms, between finished pieces.
export function archiveSession(asset, pin, {direct, relay = [], fetchFile, signal, network,
    relayReady = () => true, refreshRelay = () => {}, onRoute = () => {}, drain, atSavePoint = async () => {},
    onInflight = () => {}}) {
  let lanes = 6, previousRate = 0, growth = true, sampled = false, preferred = direct[0], windowsSinceSample = 0;
  const relayURLs = new Set(relay);
  const cooldown = routeCooldowns(network);
  // Relay routes ordered by sampled speed. A route that returns wrong or
  // unusable data is dropped; a throttled or dropped request moves the next
  // pieces to another relay route. The slow default mirror is the last resort
  // for a piece, so one relay hiccup no longer costs a 4 MiB piece at 0.46 MB/s.
  let ranked = [...relay];
  const dropped = new Set();
  const liveRelays = () => ranked.filter(url => !dropped.has(url));
  const routes = () => {
    const ready = relayReady();
    return [...new Set([preferred, ...(ready ? liveRelays() : []), ...direct])]
      .filter(url => !dropped.has(url) && (ready || !relayURLs.has(url)));
  };
  // Bytes each kind of route served in the current window, and failed relay
  // requests. A capped relay fails before any bytes, so pieces fall through to
  // the direct mirror while the relay still counts as ready.
  let served = {relay: 0, direct: 0, misses: 0}, relayFailing = false, reported;
  // Pieces in flight. Their received bytes are lost if the download stops
  // before they are journaled.
  const reading = new Set();
  // Recent speed of one request, in bytes per ms, for pieces that just started.
  let streamRate = 0, inflightReported = 0;
  function report(fast) {
    if (!relay.length || fast === reported) return;
    reported = fast;
    diag("route-flag", {asset: asset.id, fast});
    onRoute({fast});
  }
  function rotate(url) {
    const relays = liveRelays();
    if (!relays.length) return direct[0];
    const next = relays[(relays.indexOf(url) + 1) % relays.length];
    return next === undefined ? relays[0] : next;
  }
  diag("session", {asset: asset.id, mb: +(asset.size_bytes / 1e6).toFixed(1),
    direct: direct.map(routeLabel), relay: relay.map(routeLabel)});

  async function read(url, index, length, requestSignal) {
    const start = index * pin.size;
    const range = {start, end: start + length - 1, total: asset.size_bytes};
    const bytes = new Uint8Array(length);
    let cursor = 0;
    const began = performance.now();
    const entry = {length, received: 0, began};
    reading.add(entry);
    try {
      await streamRequest(url, range, length, fetchFile, requestSignal, chunk => {
        bytes.set(chunk, cursor);
        cursor += chunk.byteLength;
        entry.received = cursor;
        if (performance.now() - inflightReported >= 250) {
          inflightReported = performance.now();
          onInflight();
        }
      });
      if (!await pin.matches(index, bytes)) throw new SourceError("Publisher piece SHA-1 mismatch");
    } catch (error) {
      if (relayURLs.has(url) && error.name !== "AbortError") served.misses++;
      cooldown.defer(url, error.retryAfterMs ?? (relayURLs.has(url) && error.status === 429 ? 60_000 : 0));
      diag("request", {asset: asset.id, piece: index, route: routeLabel(url), ok: false, got: cursor,
        ms: Math.round(performance.now() - began), status: error.status, connection: Boolean(error.connection),
        error: error.name === "AbortError" ? "aborted" : error.message});
      throw error;
    } finally {
      reading.delete(entry);
    }
    const ms = performance.now() - began;
    served[relayURLs.has(url) ? "relay" : "direct"] += length;
    if (ms > 0) streamRate = streamRate ? streamRate * 0.7 + length / ms * 0.3 : length / ms;
    diag("request", {asset: asset.id, piece: index, route: routeLabel(url), ok: true, bytes: length,
      ms: Math.round(ms), mbps: +(length / 1e6 / (ms / 1000)).toFixed(2)});
    return bytes;
  }

  async function select(index, length, requestSignal, accept) {
    sampled = true;
    windowsSinceSample = 0;
    // Once a relay route answers, the default mirror's sample gets at most
    // twice that time (at least 3 s). Waiting for it cost a real build 22 s at
    // 0.19 MB/s before every first window.
    const baselineStop = new AbortController();
    const measure = async url => {
      if (dropped.has(url) || cooldown.waiting(url)) return null;
      const start = performance.now();
      // A nonresponsive optional peer must not block the default route.
      const probeSignal = relayURLs.has(url) ?
        AbortSignal.any([requestSignal, AbortSignal.timeout(20_000)]) :
        AbortSignal.any([requestSignal, baselineStop.signal]);
      try {
        const bytes = await read(url, index, length, probeSignal);
        return {url, bytes, elapsed: performance.now() - start};
      } catch (error) {
        requestSignal.throwIfAborted();
        if (!(error instanceof SourceError) && !probeSignal.aborted) throw error;
        return null;
      }
    };
    const probes = [preferred, ...relay].map(measure);
    let deadline;
    for (const probe of probes.slice(1)) {
      probe.then(result => {
        if (result && !deadline) deadline = setTimeout(() => baselineStop.abort(), Math.max(3_000, 2 * result.elapsed));
      }, () => {});
    }
    const [baseline, ...peers] = await Promise.all(probes).finally(() => clearTimeout(deadline));
    const answered = peers.filter(Boolean).sort((a, b) => a.elapsed - b.elapsed);
    ranked = [...answered.map(peer => peer.url), ...relay.filter(url => !answered.some(peer => peer.url === url))];
    const fastest = answered[0];
    diag("sample", {asset: asset.id, piece: index, baseline: baseline ? Math.round(baseline.elapsed) + "ms" : "failed",
      relays: Object.fromEntries(relay.map(url => {
        const peer = peers.find(entry => entry?.url === url);
        return [routeLabel(url), peer ? Math.round(peer.elapsed) + "ms" : "failed"];
      }))});
    if (fastest && (!baseline || fastest.elapsed * 1.25 < baseline.elapsed)) preferred = fastest.url;
    diag("route", {asset: asset.id, preferred: routeLabel(preferred), reason: "sampled"});
    // A relay that answered but lost the sample leaves the faster direct route in use.
    relayFailing = !fastest;
    report(!relayFailing);
    const sample = baseline || fastest;
    if (!sample) return false;
    await accept(index, sample.bytes);
    return true;
  }

  async function transfer(part, {restore, accept, ordered}) {
    const first = part.start / pin.size;
    const limit = first + Math.ceil(part.bytes / pin.size);
    const controller = new AbortController();
    const requestSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
    // The previous window's write chain. Each window's writes queue behind it,
    // which keeps positioned writes and the in-order SHA-256 sequential.
    let pending = Promise.resolve();
    try {
      for (let start = first; start < limit; start += WINDOW_PIECES) {
        requestSignal.throwIfAborted();
        if (drain?.aborted) {
          await pending;
          await atSavePoint();
        }
        const end = Math.min(start + WINDOW_PIECES, limit);
        const window = new Array(end - start);
        let committed = start, written = pending, transferred = 0, backoff = false, writeMs = 0;
        const began = performance.now();
        const lengthOf = index => Math.min(pin.size, asset.size_bytes - index * pin.size);
        // Serialize positioned writes and advance SHA-256 over the contiguous prefix.
        function write(index, bytes, persist) {
          written = written.then(async () => {
            requestSignal.throwIfAborted();
            const writeBegan = performance.now();
            await accept(index, bytes, persist);
            const took = performance.now() - writeBegan;
            writeMs += took;
            if (took > 250) diag("slow-write", {asset: asset.id, piece: index, ms: Math.round(took), persist});
            window[index - start] = bytes;
            while (window[committed - start]) {
              ordered(window[committed - start]);
              window[committed - start] = null;
              committed++;
            }
          });
          // Queued writes outlive a lane that stops on pause or failure; mark the
          // chain observed so a late rejection is not unhandled. Draining it with
          // "await written" still raises the error.
          written.catch(() => {});
          return written;
        }

        // Sample on the first window, and again every 8 windows (512 MiB) while
        // the default mirror is preferred, so a relay outage at the start of an
        // archive does not pin the whole archive to 0.46 MB/s.
        const ready = relay.length > 0 && relayReady();
        if (relay.length && !ready) {
          if (relayURLs.has(preferred)) preferred = direct[0];
          sampled = false;
          relayFailing = true;
          report(false);
          void Promise.resolve(refreshRelay()).catch(() => {});
        }
        served = {relay: 0, direct: 0, misses: 0};
        const resample = sampled && !relayURLs.has(preferred) && ++windowsSinceSample >= 8;
        let needSample = ready && (!sampled || resample), sampling = null;
        if (needSample && lengthOf(start) === pin.size) {
          const saved = await restore(start, lengthOf(start));
          if (saved) await write(start, saved, false);
          else {
            await select(start, lengthOf(start), requestSignal, (index, bytes) => write(index, bytes, true));
            needSample = false;
          }
        }
        let remaining = Array.from({length: end - committed}, (_, i) => committed + i);
        let attempt = 0;
        while (remaining.length) {
          let cursor = 0, fatal, throttled = false;
          const failed = [];
          async function lane() {
            while (!throttled && cursor < remaining.length && !drain?.aborted) {
              requestSignal.throwIfAborted();
              const index = remaining[cursor++];
              const length = lengthOf(index);
              const saved = await restore(index, length);
              if (saved) {
                await write(index, saved, false);
                continue;
              }
              // On Resume the window's first piece is usually already on the
              // drive, so the route was never sampled and a real build stayed on
              // the 0.36 MB/s default mirror. Sample on the first piece that needs
              // downloading; other lanes wait for the choice.
              if (needSample && length === pin.size) {
                sampling ??= select(index, length, requestSignal, (i, bytes) => write(i, bytes, true))
                  .then(accepted => accepted ? index : null);
                if (await sampling === index) {
                  transferred += length;
                  continue;
                }
              }
              let failure, bytes;
              for (const url of routes()) {
                if (dropped.has(url) || cooldown.waiting(url)) continue;
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
                    const busy = error.status === 429 || error.status === 503 || error.connection;
                    if (!busy) {
                      dropped.add(url);
                      diag("drop", {asset: asset.id, route: routeLabel(url), reason: error.status ? "HTTP " + error.status : error.message});
                    }
                    if (preferred === url) {
                      preferred = rotate(url);
                      diag("route", {asset: asset.id, preferred: routeLabel(preferred), reason: busy ? "busy" : "dropped"});
                    }
                  }
                }
              }
              if (bytes) {
                transferred += length;
                // Queue the ordered write and keep downloading; the window drains
                // the queue before it ends. Awaiting here made a real USB build
                // alternate between downloading and writing (2.3 of 4.2 s writing).
                write(index, bytes, true);
              } else {
                failure ??= new SourceError("Download sources are cooling down", {status: 429});
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
          if (fatal) {
            await written.catch(() => {});
            throw fatal;
          }
          if (drain?.aborted && (failed.length || cursor < remaining.length)) {
            // Every piece that arrived is journaled once its write finishes.
            await written;
            await atSavePoint();
          }
          if (!failed.length) break;
          remaining = [...failed.map(({index}) => index), ...remaining.slice(cursor)];
          lanes = Math.max(MIN_LANES, Math.floor(lanes / 2));
          if ((failed.some(({error}) => error.connection) || network.offline()) &&
              (diag("wait", {asset: asset.id, reason: "offline or connection lost"}), await network.waitForConnection())) continue;
          if (++attempt >= 3) throw failed[0].error;
          diag("wait", {asset: asset.id, reason: throttled ? "throttled" : "retry", attempt, failed: failed.length,
            ms: throttled ? 1_000 * 2 ** attempt : "default"});
          await cooldown.delay(routes().filter(url => !dropped.has(url)), throttled ? 1_000 * 2 ** attempt : undefined);
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
        // Let this window's writes finish while the next window downloads, but
        // never run more than one window ahead of the drive.
        await pending;
        pending = written;
        if (served.relay) relayFailing = false;
        else if (served.misses) {
          // Every relay request in this window failed (a capped Worker answers
          // without CORS). Try the direct mirror first until the next sample,
          // so each piece stops paying for a failed request and a lane backoff.
          relayFailing = true;
          if (relayURLs.has(preferred)) {
            preferred = direct[0];
            diag("route", {asset: asset.id, preferred: routeLabel(preferred), reason: "relay failing"});
          }
        }
        if (served.relay || served.direct) {
          report(served.relay >= served.direct || !relayFailing && relayReady() && liveRelays().length > 0);
        }
        const windowMs = performance.now() - began;
        diag("window", {asset: asset.id, pieces: start + "-" + (end - 1), mb: +(transferred / 1e6).toFixed(1),
          ms: Math.round(windowMs), mbps: +(transferred / 1e6 / Math.max(windowMs / 1000, 0.001)).toFixed(2),
          writeMs: Math.round(writeMs), lanesNext: lanes, backoff, attempts: attempt, preferred: routeLabel(preferred)});
      }
      // The caller closes the writable after this returns: drain every write.
      await pending;
    } catch (error) {
      diag("transfer-error", {asset: asset.id, error: error.name === "AbortError" ? "aborted" : error.message});
      throw error;
    } finally {
      controller.abort();
    }
  }
  // What stopping now would discard (lost), what is still to arrive (toSave),
  // and the seconds until the slowest piece in flight is kept, from each
  // request's own speed (servers often limit each connection).
  transfer.inflight = () => {
    let lost = 0, toSave = 0, ms = 0;
    const now = performance.now();
    for (const entry of reading) {
      lost += entry.received;
      toSave += entry.length - entry.received;
      const elapsed = now - entry.began;
      const speed = entry.received && elapsed >= 500 ? entry.received / elapsed : streamRate;
      ms = Math.max(ms, speed ? (entry.length - entry.received) / speed : Infinity);
    }
    return {lost, toSave, seconds: Number.isFinite(ms) ? ms / 1000 : undefined};
  };
  return transfer;
}
