/* Range reader for the openZIM file format. */
(function (root) {
  "use strict";

  const decode = new TextDecoder();
  const encode = new TextEncoder();
  const headerSize = 80;
  const maxCluster = 32 * 1024 * 1024;
  const cacheLimit = 2 * maxCluster;
  const absent = 0xffffffff;
  const check = (test, message = "Invalid ZIM data", code = "invalid") => {
    if (!test) throw Object.assign(new Error(message), {code});
  };
  const u64 = (view, at) => Number(view.getBigUint64(at, true));
  const viewOf = bytes => new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const compare = (left, right) => {
    for (let i = 0; i < Math.min(left.length, right.length); i++) {
      if (left[i] !== right[i]) return left[i] - right[i];
    }
    return left.length - right.length;
  };

  // Check the frame and window before fzstd allocates its history buffer.
  // A ZIM cluster contains one frame. Reject trailing frames and oversized output.
  function decompress(bytes) {
    const view = viewOf(bytes);
    check(bytes.length >= 6 && view.getUint32(0, true) === 0xfd2fb528);
    const flags = bytes[4];
    const single = Boolean(flags & 32);
    const width = [single ? 1 : 0, 2, 4, 8][flags >> 6];
    const start = (single ? 5 : 6) + [0, 1, 2, 4][flags & 3];
    check(bytes.length >= start + width);
    const size = width === 8 ? u64(view, start) : width === 4 ? view.getUint32(start, true) :
      width === 2 ? view.getUint16(start, true) + 256 : width ? bytes[start] : 0;
    const base = 2 ** (10 + (bytes[5] >> 3));
    const window = single ? size : base + base / 8 * (bytes[5] & 7);
    check(size <= maxCluster && window <= maxCluster, "ZIM cluster exceeds the reader limit", "unsupported");

    let at = start + width, last;
    do {
      check(at + 3 <= bytes.length);
      const block = bytes[at] | bytes[at + 1] << 8 | bytes[at + 2] << 16;
      last = block & 1;
      at += 3 + ((block & 6) === 2 ? 1 : block >> 3);
    } while (!last);
    check(at + (flags & 4 ? 4 : 0) === bytes.length);

    const chunks = [];
    let length = 0;
    const decoder = root.fzstd || (typeof module !== "undefined" && require("./fzstd.js"));
    new decoder.Decompress(chunk => {
      length += chunk.length;
      check(length <= maxCluster && (!width || length <= size), "ZIM cluster exceeds the reader limit", "unsupported");
      if (chunk.length) chunks.push(chunk);
    }).push(bytes, true);
    check(!width || length === size);
    const result = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      result.set(chunk, offset);
      offset += chunk.length;
    }
    return result;
  }

  class Zim {
    constructor(parts) {
      this.parts = Array.isArray(parts) ? parts : [parts];
      this.size = this.parts.reduce((offset, part) => offset + part.size, 0);
      this.bytesRead = 0;
      this.clusters = new Map();
      this.cachedBytes = 0;
    }

    slice(offset, length, type = "", account = true) {
      check(Number.isSafeInteger(offset) && Number.isSafeInteger(length) &&
        offset >= 0 && length >= 0 && offset + length <= this.size);
      if (account) this.bytesRead += length;
      let base = 0, remaining = length;
      const slices = [];
      for (const part of this.parts) {
        const end = base + part.size;
        if (!remaining) break;
        if (offset < end) {
          const take = Math.min(remaining, end - offset);
          slices.push(part.slice(offset - base, offset - base + take, type));
          remaining -= take;
          offset += take;
        }
        base = end;
      }
      return slices.length === 1 ? slices[0] : new Blob(slices, {type});
    }
    async bytes(offset, length) {
      return new Uint8Array(await this.slice(offset, length).arrayBuffer());
    }
    async view(offset, length) {
      return viewOf(await this.bytes(offset, length));
    }

    async init() {
      const header = await this.view(0, headerSize);
      check(header.getUint32(0, true) === 72173914, "Invalid ZIM header");
      this.major = header.getUint16(4, true);
      this.minor = header.getUint16(6, true);
      check([5, 6].includes(this.major) && this.minor <= 3, "Unsupported ZIM version", "unsupported");
      this.entryCount = header.getUint32(24, true);
      this.clusterCount = header.getUint32(28, true);
      this.pathPointers = u64(header, 32);
      this.titlePointers = u64(header, 40);
      this.clusterPointers = u64(header, 48);
      const mimeOffset = u64(header, 56);
      this.mainPage = header.getUint32(64, true);
      this.end = u64(header, 72) || this.size;
      const table = (start, length) => start >= headerSize && start + length <= this.end;
      check(this.end <= this.size && this.entryCount && this.clusterCount &&
        table(this.pathPointers, this.entryCount * 8) && table(this.clusterPointers, this.clusterCount * 8) &&
        table(mimeOffset, 1) && (this.mainPage === absent || this.mainPage < this.entryCount));
      this.mimes = [];
      const raw = await this.strings(mimeOffset, bytes => {
        if (bytes[0] === 0) return 1;
        return bytes.findIndex((byte, index) => byte === 0 && bytes[index + 1] === 0) + 1;
      });
      this.mimes = decode.decode(raw.subarray(0, -1)).split("\0");
      return this;
    }

    async strings(offset, endpoint) {
      let raw = new Uint8Array();
      while (raw.length < 128 * 1024 && offset + raw.length < this.end) {
        const count = Math.min(raw.length || 256, this.end - offset - raw.length);
        const next = new Uint8Array(raw.length + count);
        next.set(raw);
        next.set(await this.bytes(offset + raw.length, count), raw.length);
        raw = next;
        const end = endpoint(raw);
        if (end > 0) return raw.subarray(0, end);
      }
      throw Error("Unterminated ZIM entry");
    }

    async entry(index) {
      check(index >= 0 && index < this.entryCount);
      const pointer = u64(await this.view(this.pathPointers + 8 * index, 8), 0);
      check(pointer >= headerSize);
      let pathEnd;
      const raw = await this.strings(pointer, bytes => {
        const start = bytes[0] === 255 && bytes[1] === 255 ? 12 : 16;
        pathEnd = bytes.indexOf(0, start);
        if (pathEnd < 0) return 0;
        return bytes.indexOf(0, pathEnd + 1) + 1;
      });
      const view = viewOf(raw);
      const mime = view.getUint16(0, true);
      const redirect = mime === 0xffff;
      const pathBytes = raw.subarray(redirect ? 12 : 16, pathEnd);
      const titleBytes = raw.subarray(pathEnd + 1, -1);
      return {index, ns: String.fromCharCode(raw[3]), path: decode.decode(pathBytes),
        title: decode.decode(titleBytes.length ? titleBytes : pathBytes), pathBytes,
        titleBytes: titleBytes.length ? titleBytes : pathBytes, mime: this.mimes[mime],
        redirect: redirect ? view.getUint32(8, true) : null,
        cluster: redirect ? null : view.getUint32(8, true), blob: redirect ? null : view.getUint32(12, true)};
    }

    async lookup(count, at, order) {
      let low = 0, high = count - 1;
      while (low <= high) {
        const mid = Math.floor((low + high) / 2);
        const current = await at(mid);
        const sign = order(current);
        if (!sign) return current;
        if (sign < 0) low = mid + 1;
        else high = mid - 1;
      }
      return null;
    }
    contentNamespace() {
      return this.minor === 0 ? "A" : "C";
    }
    async find(ns, path) {
      const wanted = encode.encode(path);
      return this.lookup(this.entryCount, index => this.entry(index),
        entry => entry.ns.charCodeAt(0) - ns.charCodeAt(0) || compare(entry.pathBytes, wanted));
    }
    async findTitle(title) {
      const wanted = encode.encode(title);
      const ns = this.contentNamespace();
      const listing = this.minor > 0 && await this.find("X", "listing/titleOrdered/v1");
      if (listing) {
        const index = await this.blob(listing, false);
        check(index.size % 4 === 0);
        const match = await this.lookup(index.size / 4, async offset => {
          const bytes = await index.slice(offset * 4, offset * 4 + 4).arrayBuffer();
          this.bytesRead += 4;
          return this.entry(new DataView(bytes).getUint32(0, true));
        }, entry => compare(entry.titleBytes, wanted));
        if (match) return match;
      }
      if (this.titlePointers >= headerSize && this.titlePointers + 4 * this.entryCount <= this.end) {
        return this.lookup(this.entryCount, async index =>
          this.entry((await this.view(this.titlePointers + index * 4, 4)).getUint32(0, true)),
        entry => entry.ns.charCodeAt(0) - ns.charCodeAt(0) || compare(entry.titleBytes, wanted));
      }
      return null;
    }
    async resolve(entry) {
      const seen = new Set();
      while (entry && entry.redirect !== null) {
        check(!seen.has(entry.index) && seen.size < 32, "Invalid ZIM redirect");
        seen.add(entry.index);
        entry = await this.entry(entry.redirect);
      }
      return entry;
    }
    async get(path, {title, ns = this.contentNamespace()} = {}) {
      const found = path === "@main"
        ? this.mainPage === absent ? await this.find("W", "mainPage") : await this.entry(this.mainPage)
        : await this.find(ns, path) || (title ? await this.findTitle(title) : null);
      return this.resolve(found);
    }

    async cluster(number) {
      check(number >= 0 && number < this.clusterCount);
      const cached = this.clusters.get(number);
      if (cached) {
        this.clusters.delete(number);
        this.clusters.set(number, cached);
        return cached;
      }
      const hasNext = number + 1 < this.clusterCount;
      const pointers = await this.view(this.clusterPointers + 8 * number, hasNext ? 16 : 8);
      const start = u64(pointers, 0);
      const end = hasNext ? u64(pointers, 8) : this.end;
      check(start >= headerSize && start < end - 1 && end <= this.end);
      const info = (await this.bytes(start, 1))[0];
      const compression = info & 15;
      const width = info & 16 ? 8 : 4;
      const length = end - start - 1, base = start + 1;
      if (compression <= 1) return {base, length, width};
      check(compression === 5 && length <= maxCluster, "Unsupported ZIM cluster compression or size", "unsupported");
      const data = decompress(await this.bytes(base, length));
      while (this.cachedBytes + data.length > cacheLimit) {
        const oldest = this.clusters.keys().next().value;
        this.cachedBytes -= this.clusters.get(oldest).data.length;
        this.clusters.delete(oldest);
      }
      this.clusters.set(number, {data, length: data.length, width});
      this.cachedBytes += data.length;
      return this.clusters.get(number);
    }

    async blob(entry, account = true) {
      check(entry && entry.mime && entry.blob !== null);
      const cluster = await this.cluster(entry.cluster);
      const {width, length, base, data} = cluster;
      const read = width === 8 ? u64 : (view, offset) => view.getUint32(offset, true);
      const start = entry.blob * width;
      check(start + 2 * width <= length);
      const table = read(data ? viewOf(data) : await this.view(base, width), 0);
      check(table % width === 0 && start + 2 * width <= table && table <= length);
      const view = data ? viewOf(data.subarray(start)) : await this.view(base + start, 2 * width);
      const first = read(view, 0), last = read(view, width);
      check(first >= table && first <= last && last <= length);
      return data ? new Blob([data.subarray(first, last)], {type: entry.mime})
        : this.slice(base + first, last - first, entry.mime, account);
    }
  }

  if (typeof module !== "undefined" && module.exports) module.exports = {Zim};
  else root.OWLZim = {Zim};
})(globalThis);
