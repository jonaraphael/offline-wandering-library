#!/usr/bin/env node
/* Compile impact-ordered postings over the existing physical search chunks. */
'use strict';
const {createHash} = require('node:crypto');
const {readFileSync, writeFileSync, mkdirSync} = require('node:fs');
const {join} = require('node:path');
const {gzipSync, gunzipSync} = require('node:zlib');
const rank = require('../src/owl/templates/rank.js');

function payload(data) {
  return JSON.parse(data.slice(data.indexOf('(') + 1, -3));
}

function varint(n, bytes) {
  while (n > 127) {
    bytes.push((n & 127) | 128);
    n >>>= 7;
  }
  bytes.push(n);
}

function packed(rows) {
  const data = [];
  for (let impact = 15; impact > 0; impact--) {
    const ids = rows.filter(([, score]) => score === impact).map(([id]) => id).sort((a, b) => a - b);
    if (!ids.length) continue;
    const limit = Math.min(ids.length, 24);
    varint(impact, data);
    varint(limit, data);
    let previous = 0;
    for (const id of ids.slice(0, limit)) {
      varint(id - previous, data);
      previous = id;
    }
  }
  return Buffer.from(data);
}

function boost(records, postings, vocabulary) {
  const terms = new Map();
  function add(term, weight) {
    if (weight <= 1 && !vocabulary.has(term)) return;
    const row = terms.get(term);
    if (row) {
      row[0] = Math.max(row[0], weight);
      row[1]++;
    } else terms.set(term, [weight, 1]);
  }
  for (const [term, hits] of Object.entries(postings)) {
    for (const hit of hits) add(term, hit & 15);
  }
  // Cheap title entries keep fewer terms to keep the shared index small.
  // The per-chunk Bloom and complete title rows remain on the drive.
  for (const row of records) {
    if (!row[5]) continue;
    const title = row[0] ?? row[1].split('/').at(-1).replace(/_/g, ' ');
    // The main title's match takes precedence over redirect spellings.
    for (const term of rank.terms(title)) if (vocabulary.has(term)) add(term, row[4] ? 2 : 4);
  }
  return terms;
}

function compile(source, target) {
  const manifest = JSON.parse(readFileSync(join(source, 'manifest.json')));
  const model = payload(readFileSync(join(source, 'model.js'), 'utf8'));
  const vocabulary = new Set(model.vocab.filter(word => /^[\p{L}\p{N}]{3,}$/u.test(word)).flatMap(rank.terms));
  const parts = new Map();
  for (const [pool, shard] of Object.entries({...manifest.shared, ...manifest.sources})) {
    for (const [number, pin] of (shard.parts || []).entries()) {
      if (!parts.has(pin.sha256)) parts.set(pin.sha256, {
        path: pin.path || 'sources/' + pool + '/' + String(number).padStart(5, '0') + '.js',
        vectors: pin.vectors,
        records: pin.records,
      });
    }
  }
  mkdirSync(target, {recursive: true});
  const ids = Object.create(null);
  const dictionary = new Map();
  const digests = [...parts.keys()].sort();
  for (const [offset, digest] of digests.entries()) {
    const id = offset + 1;
    const {path, vectors, records: count} = parts.get(digest);
    const data = readFileSync(join(source, path));
    if (createHash('sha256').update(data).digest('hex') !== digest) throw Error('Invalid source ' + path);
    ids[digest] = id;
    const block = payload(data.toString('utf8'));
    const {records, postings} = JSON.parse(gunzipSync(Buffer.from(Array.isArray(block) ? block[2] : block, 'base64')));
    const terms = boost(records, postings, vocabulary);
    for (const [term, [weight, frequency]] of terms) {
      if (frequency === 1 && weight < 8 && !vocabulary.has(term)) continue;
      if (!dictionary.has(term)) dictionary.set(term, []);
      const headings = weight >= 8 ? 3 : weight >= 4 ? 2 : 1;
      const density = Math.max(0, Math.min(6, 5 + Math.round(Math.log2(frequency * 450 / count))));
      const impact = Math.min(15, headings + density + (weight >= 8 ? 1 : 0) + (vectors ? 3 : 0));
      dictionary.get(term).push([id, impact]);
    }
    if (offset % 500 === 0) console.error('Indexed', offset + 1, '/', digests.length);
  }
  const partitions = Array.from({length: 256}, () => []);
  for (const [term, rows] of dictionary) {
    if (term.length > 64 || !vocabulary.has(term) && rows.length < 2) continue;
    const bucket = rank.hashTerm(term) >>> 24;
    partitions[bucket].push([term, packed(rows), rows.length]);
  }
  const files = {};
  for (const [bucket, rows] of partitions.entries()) {
    if (!rows.length) continue;
    rows.sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
    const name = bucket.toString(16).padStart(2, '0') + '.js';
    const blocks = [];
    for (const [term, posts, count] of rows) {
      const word = Buffer.from(term);
      const header = [];
      varint(word.length, header);
      varint(posts.length, header);
      varint(count, header);
      blocks.push(Buffer.from(header), word, posts);
    }
    const zip = gzipSync(Buffer.concat(blocks), {level: 9});
    const script = 'globalThis.OWLImpactBlock(' + JSON.stringify(zip.toString('base64')) + ');\n';
    writeFileSync(join(target, name), script);
    files[name] = {bytes: Buffer.byteLength(script), sha256: createHash('sha256').update(script).digest('hex')};
  }
  writeFileSync(join(target, 'manifest.json'), JSON.stringify({version: 1, ids, files}) + '\n');
  return {chunks: parts.size, terms: partitions.reduce((sum, rows) => sum + rows.length, 0),
    bytes: Object.values(files).reduce((sum, file) => sum + file.bytes, 0)};
}

if (require.main === module) {
  const [, , source, target] = process.argv;
  if (!source || !target) throw Error('Usage: build_impact_routes.cjs catalog/search output');
  console.log(JSON.stringify(compile(source, target)));
}
