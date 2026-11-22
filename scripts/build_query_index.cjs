#!/usr/bin/env node
/* Compile a composed drive's pinned shards into term-keyed, bounded classic scripts. */
'use strict';
const {readFileSync, readdirSync, statSync, writeFileSync, mkdirSync, rmSync} = require('node:fs');
const {join, dirname} = require('node:path');
const {gzipSync, gunzipSync} = require('node:zlib');
const {createHash} = require('node:crypto');
const rank = require('../src/owl/templates/rank.js');
const index = require('../src/owl/templates/query-index.js');

const POST_BYTES = 48_000;
const RUN_ROWS = 500_000;
const BUCKETS = 64;

function payload(path, callback) {
  const text = readFileSync(path, 'utf8');
  const prefix = 'globalThis.' + callback + '(';
  if (!text.startsWith(prefix) || !text.endsWith(');\n')) throw Error('Invalid search script ' + path);
  return JSON.parse(text.slice(prefix.length, -3));
}

function postingBytes(values, limit = Infinity) {
  let previous = 0;
  const result = [];
  let bytes = [];
  for (const value of values) {
    if (bytes.length + 5 > limit) {
      result.push(Buffer.from(bytes).toString('base64'));
      bytes = [];
      previous = 0;
    }
    let delta = value - previous;
    if (!Number.isInteger(value) || delta < 0 || value > 0xffffffff) throw Error('Search postings are not sorted');
    previous = value;
    while (delta > 127) {
      bytes.push((delta & 127) | 128);
      delta = Math.floor(delta / 128);
    }
    bytes.push(delta);
  }
  if (bytes.length) result.push(Buffer.from(bytes).toString('base64'));
  return result;
}

function partList(selection) {
  const parts = new Map();
  for (const [source, asset] of selection.sources.entries()) {
    for (const [number, part] of asset.parts.entries()) {
      const pool = part.pool || asset.sha256;
      const offset = part.number ?? number;
      const path = part.path || 'sources/' + pool + '/' + String(offset).padStart(5, '0') + '.js';
      if (!/^(?:chunks\/[a-f0-9]{64}|sources\/[a-f0-9]{64}\/\d{5})\.js$/.test(path))
        throw Error('Invalid drive shard address ' + path);
      if (!parts.has(path)) parts.set(path, {path, pool, offset, users: [], bytes: part.bytes});
      parts.get(path).users.push([source, number]);
    }
  }
  return [...parts.values()];
}

function compile(selection, source, output, work) {
  const parts = partList(selection);
  const runs = Array.from({length: BUCKETS}, () => []);
  const codes = Array.from({length: 32}, () => ({chunks: [], rows: []}));
  const vectorParts = Array(32).fill(0);
  const terms = Object.create(null);
  mkdirSync(output, {recursive: true});
  mkdirSync(work, {recursive: true});
  if (readdirSync(output).length || readdirSync(work).length)
    throw Error('Choose empty output and work directories for the query index');
  let rowCount = 0, lastRun = 0, runNumber = 0, accumulated = new Map();

  const write = (path, value) => {
    const destination = join(output, path);
    mkdirSync(dirname(destination), {recursive: true});
    writeFileSync(destination, 'globalThis.OWLQueryBlock(' + JSON.stringify(value) + ');\n');
  };

  function spill() {
    const buckets = Array.from({length: BUCKETS}, () => []);
    for (const [term, rows] of accumulated) {
      buckets[parseInt(index.termBucket(term), 16) % BUCKETS].push([term, postingBytes(rows)[0]]);
    }
    for (const [number, bucket] of buckets.entries()) {
      if (!bucket.length) continue;
      const path = join(work, runNumber + '-' + number + '.gz');
      writeFileSync(path, gzipSync(JSON.stringify(bucket), {level: 1}));
      runs[number].push(path);
    }
    runNumber++;
    lastRun = rowCount;
    accumulated = new Map();
  }

  function writeVectors(partition) {
    const {rows, chunks} = codes[partition];
    if (!rows.length) return;
    const filename = 'v/' + partition + '-' + vectorParts[partition]++ + '.js';
    const data = Buffer.allocUnsafe(rows.length * 36);
    for (const [i, row] of rows.entries()) {
      data.writeUInt32LE(row, i * 36);
      chunks[i].copy(data, i * 36 + 4);
    }
    write(filename, data.toString('base64'));
    rows.length = chunks.length = 0;
  }

  for (const part of parts) {
    const filename = join(source, part.path);
    part.bytes = statSync(filename).size;
    const encoded = payload(filename, part.path.startsWith('chunks/') ? 'OWLShardBlob' : 'OWLShardPart');
    if (Array.isArray(encoded) && (encoded[0] !== part.pool || encoded[1] !== part.offset))
      throw Error('Wrong shard address ' + part.path);
    const {records, postings} = JSON.parse(gunzipSync(Buffer.from(Array.isArray(encoded) ? encoded[2] : encoded, 'base64')));
    part.start = rowCount;
    for (const [term, rows] of Object.entries(postings)) {
      if (!accumulated.has(term)) accumulated.set(term, []);
      const out = accumulated.get(term);
      for (const row of rows) out.push(rowCount * 16 + row);
    }
    for (const [offset, row] of records.entries()) {
      if (row[5]) {
        for (const term of rank.terms(row[0] ?? row[1].split('/').at(-1).replace(/_/g, ' '))) {
          if (!accumulated.has(term)) accumulated.set(term, []);
          accumulated.get(term).push((rowCount + offset) * 16 + 9);
        }
      } else if (row[3]) {
        const packed = Buffer.from(row[3], 'base64');
        if (packed.length !== 32) throw Error('Unexpected binary code size');
        const partition = index.vectorPartition(packed);
        const bucket = codes[partition];
        bucket.rows.push(rowCount + offset);
        bucket.chunks.push(packed);
        if (bucket.rows.length >= 16_384) writeVectors(partition);
      }
    }
    // Existing title-only postings omit title terms. Explicit body entries, if
    // any, were stored ahead of those title-derived entries within each chunk.
    for (const term of Object.keys(postings)) {
      const values = accumulated.get(term);
      const first = values.findLastIndex(value => value < rowCount * 16) + 1;
      if (values.length - first === postings[term].length) continue;
      const tail = values.splice(first).sort((a, b) => a - b);
      for (const value of tail) values.push(value);
    }
    rowCount += records.length;
    if (rowCount >= 2 ** 28) throw Error('Drive index has too many rows');
    if (rowCount - lastRun >= RUN_ROWS) spill();
  }
  if (accumulated.size) spill();
  for (let partition = 0; partition < codes.length; partition++) writeVectors(partition);

  for (const run of runs) {
    const postings = new Map();
    for (const path of run) {
      for (const [term, packed] of JSON.parse(gunzipSync(readFileSync(path)))) {
        if (!postings.has(term)) postings.set(term, []);
        const rows = postings.get(term);
        for (const value of index.postingValues(Buffer.from(packed, 'base64'))) rows.push(value);
      }
      rmSync(path);
    }
    let prefix, dictionary, ranges, pending, pendingBytes, blockNumber;
    function writePostings() {
      if (!pending.length) return;
      write('p/' + prefix + '-' + blockNumber++ + '.js', pending);
      pending = [];
      pendingBytes = 0;
    }
    function writeDictionary() {
      if (!dictionary.length) return;
      write('d/' + prefix + '-' + ranges.length + '.js', dictionary);
      ranges.push(dictionary[0][0]);
      dictionary = [];
    }
    const ordered = [...postings.keys()].map(term => [index.termBucket(term), term])
      .sort(([a, termA], [b, termB]) => a < b ? -1 : a > b ? 1 : termA < termB ? -1 : termA > termB ? 1 : 0);
    for (const [bucket, term] of ordered) {
      if (bucket !== prefix) {
        if (prefix !== undefined) { writePostings(); writeDictionary(); }
        prefix = bucket;
        ranges = terms[bucket] = [];
        dictionary = [];
        pending = [];
        pendingBytes = blockNumber = 0;
      }
      const pages = postingBytes(postings.get(term), POST_BYTES);
      if (pages.length > 1) {
        writePostings();
        dictionary.push([term, blockNumber, pages.length, 0]);
        for (const page of pages) write('p/' + prefix + '-' + blockNumber++ + '.js', [page]);
      } else {
        if (pendingBytes + pages[0].length > POST_BYTES * 4 / 3) writePostings();
        dictionary.push([term, blockNumber, 1, pending.length]);
        pending.push(pages[0]);
        pendingBytes += pages[0].length + 3;
      }
      if (dictionary.length >= 512) writeDictionary();
    }
    if (prefix !== undefined) { writePostings(); writeDictionary(); }
  }
  const selectionId = createHash('sha256').update(JSON.stringify(parts.map(part => [part.path, part.users]))).digest('hex');
  write('index.js', {version: 1, selectionId, rowCount, terms, vectors: vectorParts, parts});
  return {selectionId, rowCount, parts: parts.length, termBuckets: Object.keys(terms).length};
}

if (require.main === module) {
  const [selectionPath, source, output, work, scenario] = process.argv.slice(2);
  const selection = scenario === undefined ? payload(selectionPath, 'OWLShardSelection') :
    JSON.parse(readFileSync(selectionPath, 'utf8'))[Number(scenario)];
  console.log(JSON.stringify(compile(selection, source, output, work)));
}
module.exports = {compile, partList, postingBytes};
