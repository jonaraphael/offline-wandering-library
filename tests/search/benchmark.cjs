/* Run the shipped ranker over each chunk once for all 100 queries. */
'use strict';
const {createHash} = require('node:crypto');
const {readFile} = require('node:fs/promises');
const {join} = require('node:path');
const rank = require('../../src/owl/templates/rank.js');
const catalog = require('../../src/owl/templates/search.js');
const queries = require('./queries.json');

function payload(data, callback) {
  const prefix = 'globalThis.' + callback + '(';
  if (!data.startsWith(prefix) || !data.endsWith(');\n')) throw Error('Wrong script wrapper: ' + callback);
  return JSON.parse(data.slice(prefix.length, -3));
}

async function pin(path, metadata) {
  const data = await readFile(path);
  if (metadata.bytes !== data.length || metadata.sha256 !== createHash('sha256').update(data).digest('hex'))
    throw Error('Search payload digest differs: ' + path);
  return data;
}

async function benchmark(planPath, sourceRoot) {
  const plans = JSON.parse(await readFile(planPath, 'utf8'));
  const manifest = JSON.parse(await readFile(join(sourceRoot, 'manifest.json'), 'utf8'));
  const model = rank.model(payload((await pin(join(sourceRoot, 'model.js'), manifest.model)).toString(), 'OWLShardModel'));
  await pin(join(sourceRoot, 'model-license.txt'), manifest.license);
  if (queries.length !== 100 || new Set(queries.map(([q]) => q)).size !== 100) throw Error('Expected 100 unique probes');
  const probes = queries.map(([text, target]) => ({text, expected: new RegExp(target, 'iu'),
    terms: rank.terms(text), phrase: rank.normalize(text), vector: model(text)}));
  const scenarios = plans.map(plan => ({
    ...plan, sources: new Map(plan.sources.filter(row => !row.legacy).map(row => [row.sha256, row])),
    hits: probes.map(() => []), catalogPrepared: catalog.prepare(plan.metadata)
  }));
  const counts = {files: 2, bytes: manifest.model.bytes + manifest.license.bytes, records: 0, largest: manifest.model.bytes};
  for (const [digest, shard] of Object.entries(manifest.sources)) {
    const destinations = scenarios.filter(scenario => scenario.sources.has(digest));
    const whole = createHash('sha256');
    let count = 0;
    for (const [index, part] of shard.parts.entries()) {
      const filename = join(sourceRoot, 'sources', digest, String(index).padStart(5, '0') + '.js');
      const data = await pin(filename, part);
      counts.files++;
      counts.bytes += data.length;
      counts.largest = Math.max(counts.largest, data.length);
      count += part.records;
      whole.update(data);
      if (!destinations.length) continue;
      const bloom = atob(part.bloom);
      const selected = probes.map(probe => part.vectors > 0 || rank.mightMatch(bloom, probe.terms));
      if (!selected.some(Boolean)) continue;
      const row = payload(data.toString(), 'OWLShardPart');
      if (row[0] !== digest || row[1] !== index) throw Error('Chunk ID differs: ' + filename);
      const chunk = await rank.unpack(row[2]);
      if (chunk.records.length !== part.records || chunk.vectors.length !== part.vectors) throw Error('Record count differs: ' + filename);
      for (const [number, query] of probes.entries()) {
        if (!selected[number]) continue;
        const partHits = rank.rankPart(chunk, query.terms, query.phrase, query.vector, 30);
        if (!partHits.length) continue;
        for (const scenario of destinations) {
          const hits = scenario.hits[number];
          hits.push(...partHits.map(hit => rank.result(scenario.sources.get(digest), hit, index)));
          hits.sort(rank.order);
          if (hits.length > 120) hits.length = 120;
        }
      }
    }
    if (whole.digest('hex') !== shard.sha256 || count !== shard.records) throw Error('Shard digest or count differs: ' + digest);
    counts.records += count;
  }
  const manifestBytes = (await readFile(join(sourceRoot, 'manifest.json'))).length;
  counts.bytes += manifestBytes;
  counts.largest = Math.max(counts.largest, manifestBytes);
  counts.files++;
  if (counts.bytes > 600_000_000 || counts.largest > 50_000_000) throw Error('Repository search data exceeds its byte budgets');
  const results = scenarios.map(scenario => {
    const misses = [], zeros = [];
    const totals = {fable_hit: 0, fable_zero: 0, hit: 0, zero: 0};
    probes.forEach((query, number) => {
      const hybrid = rank.topResults(scenario.hits[number], 30);
      const metadata = catalog.search(scenario.catalogPrepared, query.text, 'all');
      const results = [...hybrid, ...metadata].slice(0, 10);
      const match = results.some(({record}) => query.expected.test([record.title, record.description, record.source_title,
        record.kind === 'article' ? record.location : ''].join(' ')));
      if (match) {
        totals.hit++;
        if (number < 40) totals.fable_hit++;
      } else {
        misses.push(query.text);
      }
      if (!results.length) {
        zeros.push(query.text);
        totals.zero++;
        if (number < 40) totals.fable_zero++;
      }
    });
    return {capacity_gb: scenario.capacity_gb, search_bytes: scenario.search_bytes, assets: scenario.selected_assets,
      shard_bytes: scenario.shard_bytes, zims: scenario.selected_zims, indexed_zims: scenario.indexed_zims,
      sampled_zims: scenario.sampled_zims, indexed_sources: scenario.sources.size, ...totals, misses, zeros};
  });
  console.log(JSON.stringify({artifact: counts, scenarios: results}, null, 2));
  if (process.argv.includes('--check')) {
    const bounds = require('./bounds.json');
    for (const row of results) {
      const bound = bounds[row.capacity_gb];
      if (row.hit < bound.hit || row.fable_hit < bound.fable_hit || row.zero > bound.zero || row.fable_zero > bound.fable_zero)
        throw Error('Search quality regressed at ' + row.capacity_gb + ' GB');
    }
  }
}

benchmark(process.argv[2], process.argv[3]).catch(error => { console.error(error); process.exitCode = 1; });
