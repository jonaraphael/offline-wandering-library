#!/usr/bin/env node
/* Derive query routes from the exact packed records without changing the shards. */
'use strict';
const {createHash} = require('node:crypto');
const {readFileSync, writeFileSync, existsSync} = require('node:fs');
const {join} = require('node:path');
const {gunzipSync} = require('node:zlib');
const {isMainThread, Worker, workerData, parentPort} = require('node:worker_threads');
const rank = require('../src/owl/templates/rank.js');

function describe(data, pin) {
  if (createHash('sha256').update(data).digest('hex') !== pin.sha256) throw Error('Unverified shard');
  const legacy = data.startsWith('globalThis.OWLShardPart(');
  const wrapper = legacy ? 'globalThis.OWLShardPart(' : 'globalThis.OWLShardBlob(';
  const packed = JSON.parse(data.slice(wrapper.length, -3));
  const {records, postings} = JSON.parse(gunzipSync(Buffer.from(legacy ? packed[2] : packed, 'base64')));
  const filter = Buffer.alloc(records.length > 100 ? 2048 : 256);
  const mask = filter.length * 8 - 1;
  const lexical = Array.from({length: records.length}, () => []);
  for (const [term, entries] of Object.entries(postings)) {
    const key = rank.hashTerm(term);
    for (const entry of entries) if (lexical[entry >>> 4].length < 200) lexical[entry >>> 4].push(key);
  }
  const vectors = Array.from({length: 8}, () => ({count: 0, sum: new Int32Array(256)}));
  function insert(key) {
    const first = key & mask, second = (key >>> 15) & mask;
    filter[first >>> 3] |= 1 << (first & 7);
    filter[second >>> 3] |= 1 << (second & 7);
  }
  for (const [index, row] of records.entries()) {
    const title = row[0] ?? row[1].split('/').at(-1).replace(/_/g, ' ');
    const normalized = rank.normalize(title);
    insert(rank.hashTerm('^' + normalized));
    const titleTerms = rank.terms(title).map(rank.hashTerm);
    const terms = row[5] ? titleTerms : lexical[index];
    // Co-occurrence routing is a score heuristic. Large passage vocabularies
    // still retain their single-term Bloom and semantic route.
    for (let left = 0; left < terms.length && left < 20; left++) {
      for (let right = left + 1; right < terms.length && right < 20; right++)
        insert(rank.pairHash(terms[left], terms[right]));
    }
    if (row[3]) {
      const code = Buffer.from(row[3], 'base64');
      const bucket = vectors[(code[0] ^ code[7] ^ code[17]) & 7];
      bucket.count++;
      for (let byte = 0; byte < code.length; byte++)
        for (let bit = 0; bit < 8; bit++) bucket.sum[byte * 8 + bit] += code[byte] & (1 << bit) ? 1 : -1;
    }
  }
  const centroids = Buffer.alloc(8 * 32);
  let written = 0;
  for (const bucket of vectors) {
    if (!bucket.count) continue;
    for (const [index, value] of bucket.sum.entries())
      if (value >= 0) centroids[written * 32 + (index >>> 3)] |= 1 << (index & 7);
    written++;
  }
  return [filter.toString('base64'), centroids.subarray(0, written * 32).toString('base64')];
}

if (!isMainThread) {
  const {root, jobs} = workerData;
  const routes = {};
  for (const [path, pin] of jobs) routes[pin.sha256] = describe(readFileSync(join(root, path), 'utf8'), pin);
  parentPort.postMessage(routes);
} else {
  const [, , root, output, old = output] = process.argv;
  if (!root || !output) throw Error('Usage: build_search_routes.cjs <catalog/search> <routes.json> [previous routes]');
  const manifest = JSON.parse(readFileSync(join(root, 'manifest.json')));
  const previous = existsSync(old) ? JSON.parse(readFileSync(old)) : {};
  const routes = {}, jobs = new Map();
  for (const [pool, shard] of Object.entries({...manifest.shared, ...manifest.sources})) {
    for (const [number, pin] of (shard.parts || []).entries()) {
      if (previous[pin.sha256]) routes[pin.sha256] = previous[pin.sha256];
      else jobs.set(pin.sha256, [pin.path || 'sources/' + pool + '/' + String(number).padStart(5, '0') + '.js', pin]);
    }
  }
  const batches = Array.from({length: 5}, () => []);
  [...jobs.values()].forEach((job, index) => batches[index % batches.length].push(job));
  Promise.all(batches.filter(batch => batch.length).map(batch => new Promise((resolve, reject) => {
    const worker = new Worker(__filename, {workerData: {root, jobs: batch}});
    worker.once('message', resolve);
    worker.once('error', reject);
  }))).then(results => {
    Object.assign(routes, ...results);
    const chunks = Object.keys(routes).sort().map(digest => JSON.stringify(digest) + ':' + JSON.stringify(routes[digest]));
    writeFileSync(output, '{\n' + chunks.join(',\n') + '\n}\n');
    console.log(Object.keys(routes).length + ' routes, ' + jobs.size + ' regenerated');
  }).catch(error => { console.error(error); process.exitCode = 1; });
}
