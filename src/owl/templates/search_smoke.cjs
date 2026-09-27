"use strict";
// Run the shipped engine against bounded reads of a completed script package.
// JSON wrappers are parsed as data; generated chunk scripts are never evaluated.
const fs = require("node:fs"), path = require("node:path");
let outputWritten = false;
function finish(value, code = 0) {
  if (outputWritten) return;
  outputWritten = true;
  process.stdout.write(JSON.stringify(value) + "\n"); process.exitCode = code;
}
function check(value, message) { if (!value) throw new Error(message); }
function readFile(name, limit) {
  const stat = fs.lstatSync(name);
  check(stat.isFile() && !stat.isSymbolicLink() && stat.size <= limit, "Unsafe or oversized smoke input");
  const fd = fs.openSync(name, "r");
  try {
    const bytes = Buffer.alloc(limit + 1), count = fs.readSync(fd, bytes, 0, bytes.length, 0);
    check(count <= limit, "Smoke input exceeded its read limit");
    return bytes.subarray(0, count).toString("utf8");
  } finally { fs.closeSync(fd); }
}
function local(root, relative) {
  check(typeof relative === "string" && !/[\\:\x00-\x1f]/.test(relative) &&
        relative.split("/").every(p => p && p !== "." && p !== ".."), "Unsafe search destination");
  let current = root;
  for (const part of relative.split("/")) {
    current = path.join(current, part);
    check(!fs.lstatSync(current).isSymbolicLink(), "Search path contains a symlink");
  }
  check(fs.statSync(current).isFile(), "Search destination is missing");
  return current;
}
(async () => {
  let input = "";
  for await (const chunk of process.stdin) {
    input += chunk; check(Buffer.byteLength(input) <= 16 * 1024 * 1024, "Smoke request exceeds its limit");
  }
  const request = JSON.parse(input), engine = require(request.runtime);
  const selected = new Map(request.assets.map(a => [a.destination, a]));
  let chunkReads = 0, readBytes = 0;
  const load = async (relative, callback, receive) => {
    check(callback === "OWLSearchChunk" || callback === "OWLSearchManifest", "Unexpected search callback");
    const script = readFile(local(request.library, relative), callback === "OWLSearchChunk" ? 1400000 : 4096);
    readBytes += Buffer.byteLength(script);
    check(readBytes <= 256 * 1024 * 1024, "Search smoke exceeded its total read budget");
    const prefix = "globalThis." + callback + "(";
    check(script.startsWith(prefix) && script.endsWith(");\n"), "Invalid local search script wrapper");
    const args = JSON.parse("[" + script.slice(prefix.length, -3) + "]");
    if (callback === "OWLSearchChunk") chunkReads++;
    return receive(...args);
  };
  const manifest = await engine.loadManifest(load);
  const index = new engine.Index(new engine.ScriptChunkFile(manifest, load));
  await index.open();
  check(index.header.documents === request.documents, "Runtime passage count differs from inventory");
  let records = 0, queries = 0, facets = 0, querySkipped = 0;
  function verify(record) {
    check(selected.has(record.destination), "Search result points outside the selected inventory");
    check(typeof record.title === "string" && typeof record.text === "string", "Invalid search record");
    check(engine.safeLink(record) !== null, "Unsafe runtime result link");
    local(request.library, record.destination);
  }
  for (const sample of request.samples) {
    const record = await index.record(index.header.docs_offset, sample.id);
    verify(record); records++;
    check(record.destination === sample.destination, "Search record and coverage asset differ");
    let term = null;
    const words = [...new Set(engine.tokens(record.title + " " + record.text))]
      .sort((a, b) => b.length - a.length).slice(0, 8);
    for (const word of words) {
      const candidate = await index.term(word);
      if (candidate && candidate[2] <= 100000 && (!term || candidate[2] < term[2])) term = candidate;
      if (term && term[2] <= 10000) break;
    }
    if (!term) { querySkipped++; continue; }
    const found = await index.search(term[0], {limit: 3, shelf: selected.get(record.destination).legacy ? "legacy" : "all"});
    check(found.matches > 0 && found.results.length > 0, "Positive runtime query returned no results");
    found.results.forEach(verify); queries++;
    for (const shelf of selected.get(record.destination).shelves) {
      const filtered = await index.search(term[0], {shelf, limit: 3});
      check(filtered.matches > 0, "Selected shelf query lost its matching passage");
      for (const result of filtered.results) {
        verify(result);
        check(selected.get(result.destination).shelves.includes(shelf), "Runtime shelf filter returned another shelf");
      }
      facets++;
    }
  }
  finish({status: queries ? "passed" : "skipped", ...(queries ? {} : {reason: "No positive query fits the bounded smoke budget"}),
          records_checked: records, positive_queries: queries, shelf_queries: facets,
          skipped_queries: querySkipped, chunk_reads: chunkReads, script_bytes_read: readBytes,
          scope: "Node runtime and local script transport; no browser or device certification"});
})().catch(error => finish({status: "failed", error: String(error.message || error).slice(0, 1500)}, 1));
