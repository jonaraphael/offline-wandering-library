
"use strict";
// The logical index engine and bounded local-script transport are tested in Node.
const OWLSearch = (() => {
  const decoder = new TextDecoder("utf-8", {fatal: true});
  const encoder = new TextEncoder();
  const MAX_READ = 1024 * 1024;
  const POSTING_BLOCK = 4096; // 48 KiB per query term; at most 32 terms.
  const FLAG_BLOCK = 65536; // One 64 KiB cache; one byte per passage.
  const SHELVES = {all: 0, textbooks: 1, "illustrated-guides": 2};
  function tokens(text) {
    return text.normalize("NFKC").toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
  }
  function compare(a, b) {
    // SQLite BINARY orders UTF-8 bytes; JS's default UTF-16 comparison differs
    // for supplementary Unicode characters. Use the on-disk ordering exactly.
    const x = encoder.encode(a), y = encoder.encode(b);
    for (let i = 0; i < Math.min(x.length, y.length); i++) {
      if (x[i] !== y[i]) return x[i] - y[i];
    }
    return x.length - y.length;
  }
  function checkInt(value, minimum = 0) {
    if (!Number.isSafeInteger(value) || value < minimum) throw new Error("Invalid or damaged index offset.");
    return value;
  }
  function offset64(view, position) {
    return checkInt(view.getUint32(position, true) + view.getUint32(position + 4, true) * 4294967296);
  }
  function safeLink(record) {
    const path = record.destination;
    if (typeof path !== "string" || /[\\:\x00-\x1f]/.test(path) || path.startsWith("/")) return null;
    const parts = path.split("/");
    if (parts.some(part => !part || part === "." || part === "..")) return null;
    let link = parts.map(encodeURIComponent).join("/");
    if (record.format === "pdf" && Number.isSafeInteger(record.page) && record.page > 0) link += "#page=" + record.page;
    return link;
  }
  function snippet(text, terms) {
    const normalized = text.normalize("NFKC").toLowerCase();
    let at = -1;
    for (const term of terms) { const i = normalized.indexOf(term); if (i >= 0 && (at < 0 || i < at)) at = i; }
    const start = Math.max(0, at - 90);
    return (start ? "…" : "") + text.slice(start, start + 340).replace(/\s+/g, " ") + (text.length > start + 340 ? "…" : "");
  }
  function resourceLabels(record) {
    const names = {textbook: "Textbook", guide: "Guide", reference: "Reference", archive: "Archive", software: "Software"};
    const labels = Object.prototype.hasOwnProperty.call(names, record.resource_type) ? [names[record.resource_type]] : [];
    if (record.illustrated) labels.push("Illustrated");
    return labels;
  }
  class TopResults {
    constructor(limit) { this.limit = limit; this.heap = []; }
    // Lowest score / largest ID is the least desirable retained result.
    less(a, b) { return a.score < b.score || (a.score === b.score && a.id > b.id); }
    add(value) {
      const heap = this.heap;
      if (heap.length < this.limit) {
        heap.push(value);
        let at = heap.length - 1;
        while (at) { const parent = (at - 1) >> 1; if (!this.less(heap[at], heap[parent])) break; [heap[at], heap[parent]] = [heap[parent], heap[at]]; at = parent; }
      } else if (this.less(heap[0], value)) {
        heap[0] = value;
        let at = 0;
        for (;;) { let next = at, left = at * 2 + 1, right = left + 1; if (left < heap.length && this.less(heap[left], heap[next])) next = left; if (right < heap.length && this.less(heap[right], heap[next])) next = right; if (next === at) break; [heap[at], heap[next]] = [heap[next], heap[at]]; at = next; }
      }
    }
    sorted() { return this.heap.sort((a, b) => b.score - a.score || a.id - b.id); }
  }
  class Index {
    constructor(file) { this.file = file; this.header = null; this.cache = new Map(); }
    async read(offset, length) {
      checkInt(offset); checkInt(length);
      if (length > MAX_READ || offset + length > this.file.size) throw new Error("Index is incomplete or damaged. Run the drive verifier.");
      const result = await this.file.slice(offset, offset + length).arrayBuffer();
      if (result.byteLength !== length) throw new Error("The drive returned incomplete data.");
      return result;
    }
    async open() {
      const prefix = await this.read(0, 12);
      if (decoder.decode(prefix.slice(0, 8)) !== "OWLIDX2\n") throw new Error("Search data does not match this viewer. Rebuild the drive if its index format differs.");
      const size = new DataView(prefix).getUint32(8, true);
      if (size > 4084) throw new Error("Invalid index header.");
      const h = JSON.parse(decoder.decode(await this.read(12, size)));
      if (h.version !== 2 || h.tokenizer !== "NFKC-lower-unicode-letter-number-v1") throw new Error("This index needs its matching SEARCH.html.");
      for (const key of ["documents", "terms", "docs_offset", "flags_offset", "lexicon_offset", "size"]) checkInt(h[key]);
      if (h.size !== this.file.size || h.docs_offset < 4096 || h.docs_offset + h.documents * 12 !== h.flags_offset || h.flags_offset + h.documents > h.lexicon_offset || h.lexicon_offset + h.terms * 12 !== h.size || !Number.isFinite(h.average_length) || h.average_length < 0) throw new Error("Invalid or truncated index. Run the drive verifier.");
      this.header = h;
      return h;
    }
    async record(table, id) {
      const pointer = new DataView(await this.read(table + id * 12, 12));
      return JSON.parse(decoder.decode(await this.read(offset64(pointer, 0), pointer.getUint32(8, true))));
    }
    async term(word) {
      if (this.cache.has(word)) return this.cache.get(word);
      let low = 0, high = this.header.terms - 1, result = null;
      while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        const value = await this.record(this.header.lexicon_offset, middle);
        if (!Array.isArray(value) || typeof value[0] !== "string") throw new Error("Invalid lexicon record.");
        const order = compare(value[0], word);
        if (!order) { checkInt(value[1], this.header.flags_offset + this.header.documents); checkInt(value[2], 1); if (value[2] > this.header.documents || value[1] + value[2] * 12 > this.header.lexicon_offset) throw new Error("Invalid posting list."); result = value; break; }
        if (order < 0) low = middle + 1; else high = middle - 1;
      }
      if (this.cache.size >= 128) this.cache.delete(this.cache.keys().next().value);
      this.cache.set(word, result);
      return result;
    }
    async search(query, options = {}) {
      if (!this.header) throw new Error("Search is still loading.");
      const words = [...new Set(tokens(query))];
      if (words.length > 32) throw new Error("Use at most 32 different search words.");
      const limit = options.limit || 50;
      if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error("Invalid result limit.");
      const shelf = options.shelf || "all";
      if (!Object.prototype.hasOwnProperty.call(SHELVES, shelf)) throw new Error("Choose All resources, Textbooks, or Illustrated guides.");
      const mask = SHELVES[shelf], flags = mask ? new FacetFlags(this) : null;
      const cancelled = () => { if (options.signal && options.signal.aborted) throw new Error("Search cancelled."); };
      const lists = [];
      for (const word of words) {
        cancelled();
        const term = await this.term(word);
        if (term) { const list = new PostingList(this, term); await list.next(); lists.push(list); }
      }
      const top = new TopResults(limit);
      let scanned = 0, matches = 0;
      while (lists.some(list => list.current !== null)) {
        cancelled();
        const id = Math.min(...lists.map(list => list.current === null ? Infinity : list.current.id));
        let score = 0, matched = 0;
        for (const list of lists) {
          if (list.current !== null && list.current.id === id) {
            const {tf, dl} = list.current;
            const idf = Math.log(1 + (this.header.documents - list.count + .5) / (list.count + .5));
            score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * dl / Math.max(1, this.header.average_length)));
            matched++;
            await list.next();
          }
        }
        if (!mask || ((await flags.get(id)) & mask)) {
          // Filter before the bounded heap: a matching textbook can rank below
          // every retained unfiltered result and must still be considered.
          top.add({id, score, matched});
          matches++;
        }
        scanned++;
        if (scanned % 1024 === 0) { if (options.progress) options.progress(scanned); await new Promise(resolve => setTimeout(resolve, 0)); }
      }
      const results = [];
      for (const result of top.sorted()) {
        cancelled();
        const record = await this.record(this.header.docs_offset, result.id);
        if (typeof record.text !== "string" || typeof record.title !== "string") throw new Error("Invalid document record.");
        results.push({...result, ...record, snippet: snippet(record.text, words)});
      }
      return {results, scanned, matches, words, shelf};
    }
  }
  class FacetFlags {
    constructor(index) { this.index = index; this.start = -1; this.block = null; }
    async get(id) {
      const start = Math.floor(id / FLAG_BLOCK) * FLAG_BLOCK;
      if (start !== this.start) {
        const length = Math.min(FLAG_BLOCK, this.index.header.documents - start);
        this.block = new Uint8Array(await this.index.read(this.index.header.flags_offset + start, length));
        this.start = start;
      }
      const value = this.block[id - this.start];
      if (value > 3) throw new Error("Invalid resource flags. Run the drive verifier.");
      return value;
    }
  }
  class PostingList {
    constructor(index, term) { this.index = index; this.offset = term[1]; this.count = term[2]; this.position = 0; this.block = null; this.blockStart = 0; this.blockLength = 0; this.current = null; this.previous = -1; }
    async next() {
      if (this.position >= this.count) { this.current = null; return; }
      if (!this.block || this.position >= this.blockStart + this.blockLength) {
        this.blockStart = this.position;
        this.blockLength = Math.min(POSTING_BLOCK, this.count - this.position);
        this.block = new DataView(await this.index.read(this.offset + this.position * 12, this.blockLength * 12));
      }
      const at = (this.position - this.blockStart) * 12;
      const id = this.block.getUint32(at, true), tf = this.block.getUint32(at + 4, true), dl = this.block.getUint32(at + 8, true);
      if (id <= this.previous || id >= this.index.header.documents || !tf || !dl) throw new Error("Invalid posting data.");
      this.current = {id, tf, dl}; this.previous = id; this.position++;
    }
  }
  const CHUNK_BYTES = 1024 * 1024;
  const MAX_CACHED_CHUNKS = 8;
  const SCRIPT_TIMEOUT_MS = 15000;
  let scriptQueue = Promise.resolve();

  function validateManifest(value) {
    const fields = ["version", "index_sha256", "size", "chunk_bytes", "chunk_count"];
    if (!value || typeof value !== "object" || Array.isArray(value) ||
        Object.keys(value).some(key => !fields.includes(key)) ||
        value.version !== 1 || typeof value.index_sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(value.index_sha256) ||
        !Number.isSafeInteger(value.size) || value.size < 4096 ||
        value.chunk_bytes !== CHUNK_BYTES || !Number.isSafeInteger(value.chunk_count) ||
        value.chunk_count < 1 || value.chunk_count > 100000000 ||
        value.chunk_count !== Math.ceil(value.size / CHUNK_BYTES)) {
      throw new Error("The local search manifest is invalid. Run the drive verifier or rebuild search.");
    }
    return Object.freeze(Object.fromEntries(fields.map(key => [key, value[key]])));
  }

  function decodeChunk(manifest, expectedId, hash, id, encoded) {
    if (hash !== manifest.index_sha256 || id !== expectedId ||
        !Number.isSafeInteger(id) || id < 0 || id >= manifest.chunk_count) {
      throw new Error("A search chunk belongs to a different index or position. Run the drive verifier.");
    }
    const length = Math.min(CHUNK_BYTES, manifest.size - id * CHUNK_BYTES);
    const padding = (3 - length % 3) % 3;
    if (typeof encoded !== "string" || encoded.length !== Math.ceil(length / 3) * 4 ||
        (padding && encoded.slice(-padding) !== "=".repeat(padding)) ||
        /[^A-Za-z0-9+/]/.test(encoded.slice(0, encoded.length - padding))) {
      throw new Error("A search chunk contains invalid or incomplete data. Run the drive verifier.");
    }
    // Check unused padding bits as well as the alphabet, without a large
    // recursive regular expression or a second base64-sized encoded copy.
    if (padding) {
      const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
      const last = alphabet.indexOf(encoded[encoded.length - padding - 1]);
      if (last < 0 || (last & (padding === 2 ? 15 : 3))) throw new Error("Invalid search chunk padding.");
    }
    const binary = atob(encoded);
    if (binary.length !== length) throw new Error("A search chunk has the wrong decoded length.");
    const bytes = new Uint8Array(length);
    for (let offset = 0; offset < length; offset++) bytes[offset] = binary.charCodeAt(offset);
    return bytes;
  }

  function classicScript(url, callbackName, receive) {
    // Classic local scripts can be embedded at file:// without fetch, XHR,
    // modules, crossOrigin, permissions, a server, or a file picker. Requests
    // share one queue so callback names cannot collide, even during retries.
    const run = () => new Promise((resolve, reject) => {
      if (typeof document === "undefined" || !document.head) {
        reject(new Error("This viewer cannot load local search scripts.")); return;
      }
      const script = document.createElement("script");
      let timer = null, settled = false, received = false, value;
      const callback = (...args) => {
        if (settled) return;
        try {
          if (received) throw new Error("A search script returned duplicate data.");
          received = true; value = receive(...args);
        } catch (error) { finish(error); }
      };
      function finish(error) {
        if (settled) return;
        settled = true;
        if (timer !== null) clearTimeout(timer);
        script.onload = script.onerror = null;
        script.remove();
        if (globalThis[callbackName] === callback) delete globalThis[callbackName];
        if (error) reject(error); else resolve(value);
      }
      globalThis[callbackName] = callback;
      script.onload = () => finish(received ? null : new Error("A local search script returned no data."));
      script.onerror = () => finish(new Error("A local search file could not be loaded. Keep the SEARCH folder beside this page."));
      script.src = url;
      timer = setTimeout(() => finish(new Error("Loading local search timed out. Retry, or use the static indexes.")), SCRIPT_TIMEOUT_MS);
      try { document.head.append(script); } catch (error) { finish(error); }
    });
    const operation = scriptQueue.then(run);
    scriptQueue = operation.then(() => undefined, () => undefined);
    return operation;
  }

  async function loadManifest(load = classicScript) {
    return load("SEARCH/manifest.js", "OWLSearchManifest", validateManifest);
  }

  class ScriptChunkFile {
    constructor(manifest, load = classicScript) {
      this.manifest = validateManifest(manifest);
      this.size = this.manifest.size;
      this.load = load;
      this.cache = new Map();
      this.pending = new Map();
      this.queue = Promise.resolve();
    }
    async chunk(id) {
      if (!Number.isSafeInteger(id) || id < 0 || id >= this.manifest.chunk_count) throw new Error("Invalid search chunk offset.");
      if (this.cache.has(id)) {
        const bytes = this.cache.get(id); this.cache.delete(id); this.cache.set(id, bytes); return bytes;
      }
      if (this.pending.has(id)) return this.pending.get(id);
      const operation = this.queue.then(async () => {
        const url = "SEARCH/chunks/" + this.manifest.index_sha256 + "/" + String(id).padStart(8, "0") + ".js";
        const bytes = await this.load(url, "OWLSearchChunk", (hash, position, encoded) => decodeChunk(this.manifest, id, hash, position, encoded));
        while (this.cache.size >= MAX_CACHED_CHUNKS) this.cache.delete(this.cache.keys().next().value);
        this.cache.set(id, bytes);
        return bytes;
      });
      this.pending.set(id, operation);
      this.queue = operation.then(() => undefined, () => undefined);
      try { return await operation; } finally { this.pending.delete(id); }
    }
    slice(start, end) {
      checkInt(start); checkInt(end);
      if (end < start || end > this.size || end - start > MAX_READ) throw new Error("Invalid or oversized search read.");
      return {arrayBuffer: async () => {
        const output = new Uint8Array(end - start);
        let offset = start;
        while (offset < end) {
          const id = Math.floor(offset / CHUNK_BYTES), bytes = await this.chunk(id);
          const within = offset - id * CHUNK_BYTES, length = Math.min(end - offset, bytes.length - within);
          if (length <= 0) throw new Error("Incomplete search chunk.");
          output.set(bytes.subarray(within, within + length), offset - start); offset += length;
        }
        return output.buffer;
      }};
    }
  }

  return {Index, tokens, safeLink, snippet, resourceLabels, ScriptChunkFile, loadManifest, validateManifest};
})();
if (typeof module !== "undefined" && module.exports) module.exports = OWLSearch;

if (typeof document !== "undefined" && document.getElementById("searchForm")) {
  const element = id => document.getElementById(id);
  let index = null, controller = null, generation = 0;
  const status = text => { element("status").textContent = text; };
  const controls = disabled => {
    element("searchButton").disabled = disabled;
    element("shelf").disabled = disabled;
  };
  const cancel = () => {
    if (controller) controller.abort();
    controller = null; generation++;
    element("cancelButton").disabled = true;
  };
  async function initialize() {
    cancel(); const ownGeneration = generation; index = null;
    controls(true); element("retryButton").hidden = true;
    element("results").replaceChildren();
    status("Loading search from this drive…");
    try {
      const manifest = await OWLSearch.loadManifest();
      const next = new OWLSearch.Index(new OWLSearch.ScriptChunkFile(manifest));
      const header = await next.open();
      if (generation !== ownGeneration) return;
      index = next; controls(false);
      status(header.documents.toLocaleString() + " indexed passages. Ready to search offline.");
    } catch (error) {
      if (generation === ownGeneration) {
        status("Search could not load. " + error.message + " Use the static indexes if this viewer blocks local scripts.");
        element("retryButton").hidden = false;
      }
    }
  }
  element("retryButton").addEventListener("click", initialize);
  element("cancelButton").addEventListener("click", () => { cancel(); status("Search cancelled. Enter words to search again."); });
  element("searchForm").addEventListener("submit", async event => {
    event.preventDefault(); if (!index) return; cancel();
    const ownGeneration = generation; controller = new AbortController();
    element("results").replaceChildren(); element("cancelButton").disabled = false;
    element("retryButton").hidden = true;
    status("Searching offline…");
    try {
      const found = await index.search(element("query").value, {shelf: element("shelf").value, signal: controller.signal, progress: count => { if (generation === ownGeneration) status("Searched " + count.toLocaleString() + " matching passages…"); }});
      if (generation !== ownGeneration) return;
      status(found.results.length ? "Showing " + found.results.length + " best passages of " + found.matches.toLocaleString() + " matches in the selected resources." : "No matching words in the selected resources. Try another word, choose All resources, or browse the static indexes.");
      for (const result of found.results) {
        const item = document.createElement("li"), heading = document.createElement("a"), meta = document.createElement("p"), context = document.createElement("p"), attribution = document.createElement("p"), path = document.createElement("p");
        const link = OWLSearch.safeLink(result); if (link) heading.href = link;
        heading.textContent = result.title + (result.page ? " · page " + result.page : "");
        meta.className = "meta"; meta.textContent = [...OWLSearch.resourceLabels(result), result.category, result.source, result.metadata_only ? "Catalog metadata only" : "", result.reader_required ? "Requires a reader" : ""].filter(Boolean).join(" · ");
        context.textContent = result.snippet;
        attribution.className = "meta"; attribution.textContent = [result.attribution, result.license ? "License: " + result.license : ""].filter(Boolean).join(" · ");
        path.className = "meta path"; path.textContent = result.destination + (result.entry ? " → " + result.entry : "");
        item.append(heading, meta, context);
        if (attribution.textContent) item.append(attribution);
        item.append(path); element("results").append(item);
      }
    } catch (error) {
      if (generation === ownGeneration) {
        status(error.message + " Retry loading search, or use the static indexes.");
        element("retryButton").hidden = false;
      }
    } finally { if (generation === ownGeneration) element("cancelButton").disabled = true; }
  });
  initialize();
}
