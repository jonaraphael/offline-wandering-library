/* Run the shipped ranker over each chunk once for catalog and passage queries. */
'use strict';
const {createHash} = require('node:crypto');
const {readFile} = require('node:fs/promises');
const {join} = require('node:path');
const rank = require('../../src/owl/templates/rank.js');
const catalog = require('../../src/owl/templates/search.js');
const queries = require('./queries.json');
const bodyQueries = require('./body-queries.json');
const heldOutQueries = require('./held-out-queries.json');
const taskQueries = require('./task-queries.json');

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
  const table = payload((await pin(join(sourceRoot, 'model.js'), manifest.model)).toString(), 'OWLShardModel');
  const weights = await Promise.all(manifest.model_parts.map(async (part, index) => {
    const path = join(sourceRoot, 'model', String(index).padStart(2, '0') + '.js');
    const [number, data] = payload((await pin(path, part)).toString(), 'OWLModelWeights');
    if (number !== index) throw Error('Model part ID differs: ' + path);
    return rank.bytes(data);
  }));
  const model = rank.model(table, weights);
  await pin(join(sourceRoot, 'model-license.txt'), manifest.license);
  if (queries.length !== 100 || new Set(queries.map(([q]) => q)).size !== 100) throw Error('Expected 100 unique probes');
  if (heldOutQueries.length !== 10 || new Set([...queries, ...heldOutQueries].map(([q]) => q)).size !== 110)
    throw Error('Expected 10 distinct held-out probes');
  const tasks = process.argv.includes("--tasks") ? [...taskQueries] : [];
  const extraIndex = process.argv.indexOf('--extra-tasks');
  if (extraIndex !== -1) tasks.push(...JSON.parse(await readFile(process.argv[extraIndex + 1], 'utf8')));
  const traceIndex = process.argv.indexOf('--task-depth');
  const taskDepth = traceIndex === -1 ? 3 : Number(process.argv[traceIndex + 1]);
  const depth = Math.max(30, taskDepth);
  const prep = (text, target) => ({text, ...target, query: rank.prepareQuery(text, model), phrase: rank.normalize(text)});
  const probes = [...queries.map(([text, target]) => prep(text, {expected: new RegExp(target, 'iu')})),
    ...bodyQueries.map(([text, asset, pages]) => prep(text, {asset, pages: new Set(pages)})),
    ...heldOutQueries.map(([text, target]) => prep(text, {expected: new RegExp(target, 'iu'), heldOut: true})),
    ...tasks.map(task => prep(task.query, {task: task.id}))];
  const quick = process.argv.includes('--quick');
  const bounded = process.argv.includes('--bounded');
  const runtime = !quick && !bounded && !process.argv.includes('--exhaustive');
  const budget = quick ? rank.readBudget : Infinity;
  const impactManifest = bounded || runtime ? JSON.parse(await readFile(join(sourceRoot, 'impact/manifest.json'))) : null;
  const impactCache = new Map();
  const readImpact = async filename => {
    if (!impactCache.has(filename)) {
      const packed = payload((await pin(join(sourceRoot, 'impact', filename), impactManifest.files[filename])).toString(), 'OWLImpactBlock');
      impactCache.set(filename, await rank.impactBlock(packed));
    }
    return impactCache.get(filename);
  };
  const evidence = [];
  if (impactManifest) {
    const sizes = Object.fromEntries(Object.entries(impactManifest.files).map(([name, pin]) => [name, pin.bytes]));
    for (const {query} of probes) evidence.push(await rank.impactEvidence(query, sizes, readImpact));
  }
  const scenarios = plans.map(plan => {
    const sources = new Map(plan.sources.filter(row => !row.legacy).map(row => [row.sha256, row]));
    const routes = probes.map(({query}, i) => {
      const planned = bounded ? rank.boundedBytes : runtime ? rank.completionBudget(plan, query) : budget;
      const route = plan.impact && Number.isFinite(planned) ? evidence[i] : undefined;
      const allowance = planned - (route?.readBytes || 0);
      return new Set(rank.rankedQueue(plan, query, 'all', allowance, route)
        .map(({asset, number}) => asset.sha256 + ':' + number));
    });
    return {...plan, sources, routes,
      hits: probes.map(() => []), catalogPrepared: catalog.prepare(plan.metadata)};
  });
  const modelFiles = [manifest.model, manifest.license, ...manifest.model_parts];
  const counts = {files: modelFiles.length, bytes: modelFiles.reduce((sum, part) => sum + part.bytes, 0), records: 0,
    largest: Math.max(...modelFiles.map(part => part.bytes)), by_format: {}};
  function formatCounts(format) {
    return counts.by_format[format] ??= {sources: 0, records: 0, vectors: 0, leads: 0,
      passages: 0, passage_vectors: 0, accepted_answers: 0};
  }
  const countedFiles = new Set();
  for (const [digest, shard] of Object.entries(manifest.sources)) {
    const destinations = scenarios.filter(scenario => scenario.sources.has(digest));
    const whole = createHash('sha256');
    let count = 0;
    const totals = formatCounts(shard.format);
    totals.sources++;
    totals.leads += shard.lead_records || 0;
    totals.passages += shard.passage_records || 0;
    totals.accepted_answers += shard.extraction?.accepted_answers || 0;
    const parts = [...(shard.shared || []).flatMap(pool => manifest.shared[pool].parts.map(
      (part, number) => ({pool, number, part}))), ...(shard.parts || []).map((part, number) => ({pool: digest, number, part}))];
    for (const [index, {pool, number, part}] of parts.entries()) {
      const filename = part.path ? join(sourceRoot, part.path) :
        join(sourceRoot, 'sources', pool, String(number).padStart(5, '0') + '.js');
      const data = await pin(filename, part);
      if (!countedFiles.has(filename)) {
        countedFiles.add(filename);
        counts.files++;
        counts.bytes += data.length;
        counts.largest = Math.max(counts.largest, data.length);
      }
      count += part.records;
      totals.vectors += part.vectors;
      totals.passage_vectors += part.passages || 0;
      whole.update(data);
      if (!destinations.length) continue;
      const address = digest + ':' + index;
      const selected = probes.map((_, number) => destinations.some(scenario => scenario.routes[number].has(address)));
      if (!selected.some(Boolean)) continue;
      const row = part.path ? [pool, number, payload(data.toString(), 'OWLShardBlob')] :
        payload(data.toString(), 'OWLShardPart');
      if (row[0] !== pool || row[1] !== number) throw Error('Chunk ID differs: ' + filename);
      const chunk = await rank.unpack(row[2]);
      if (chunk.records.length !== part.records || chunk.vectors.length !== part.vectors) throw Error('Record count differs: ' + filename);
      for (const [number, query] of probes.entries()) {
        if (!selected[number]) continue;
        const partHits = rank.rankPart(chunk, query.query, destinations[0].sources.get(digest), probes[number].task ? depth : 30);
        if (!partHits.length) continue;
        for (const scenario of destinations) {
          if (!scenario.routes[number].has(address)) continue;
          const hits = scenario.hits[number];
          hits.push(...partHits.map(hit => rank.result(scenario.sources.get(digest), hit, index)));
          rank.retainCandidates(hits, probes[number].task ? depth * 4 : 120);
        }
      }
    }
    if (whole.digest('hex') !== shard.sha256 || count !== shard.records) throw Error('Shard digest or count differs: ' + digest);
    counts.records += count;
    totals.records += count;
  }
  const manifestBytes = (await readFile(join(sourceRoot, 'manifest.json'))).length;
  const routeBytes = await readFile(join(sourceRoot, 'routes.json')).then(data => data.length, error => {
    if (error.code !== 'ENOENT') throw error;
    return 0;
  });
  counts.files += Number(routeBytes > 0);
  counts.bytes += manifestBytes + routeBytes;
  counts.largest = Math.max(counts.largest, routeBytes);
  counts.largest = Math.max(counts.largest, manifestBytes);
  counts.files++;
  for (const directory of ['impact', 'transformer']) {
    const path = join(sourceRoot, directory, 'manifest.json');
    const raw = await readFile(path).catch(error => {
      if (error.code !== 'ENOENT') throw error;
      return null;
    });
    if (!raw) continue;
    const manifest = JSON.parse(raw);
    const files = directory === 'impact' ? manifest.files : manifest;
    counts.files++;
    counts.bytes += raw.length;
    for (const [name, metadata] of Object.entries(files)) {
      const asset = await pin(join(sourceRoot, directory, name), metadata);
      counts.files++;
      counts.bytes += asset.length;
      counts.largest = Math.max(counts.largest, asset.length);
    }
  }
  if (counts.bytes > 900_000_000 || counts.largest > 50_000_000) throw Error('Repository search data exceeds its byte budgets');
  const results = scenarios.map(scenario => {
    const misses = [], zeros = [];
    const totals = {fable_hit: 0, fable_zero: 0, hit: 0, zero: 0, body_hit: 0, body_zero: 0};
    const body_misses = [], held_out_misses = [], task_results = [];
    probes.forEach((query, number) => {
      const hybrid = rank.topResults(scenario.hits[number], query.task ? depth : 30);
      const metadata = catalog.search(scenario.catalogPrepared, query.text, 'all');
      const results = catalog.mergeRanked(hybrid, metadata, 10);
      if (query.task) {
        const taskHits = catalog.mergeRanked(hybrid, metadata, taskDepth);
        task_results.push({id: query.task, results: taskHits.map(({record, score, focused}) =>
          taskDepth === 3 ? record : {...record, score, focused})});
        return;
      }
      if (query.asset) {
        const match = results.some(({record}) => record.kind === 'section' && record.asset_id === query.asset &&
          query.pages.has(Number(record.href.split('#page=')[1])) &&
          !rank.normalize(record.title + ' ' + record.source_title).includes(query.phrase));
        if (match) totals.body_hit++;
        else body_misses.push(query.text);
        if (!results.length) totals.body_zero++;
        return;
      }
      const match = results.some(({record}) => query.expected.test([record.title, record.description, record.source_title,
        record.kind === 'article' ? record.location : ''].join(' ')));
      if (query.heldOut) {
        if (!match) held_out_misses.push(query.text);
        return;
      }
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
      sampled_zims: scenario.sampled_zims, indexed_sources: scenario.sources.size, ...totals, miss_count: misses.length, misses, zeros, body_misses,
      query_count: queries.length, body_query_count: bodyQueries.length,
      held_out_hit: heldOutQueries.length - held_out_misses.length, held_out_misses,
      held_out_query_count: heldOutQueries.length, ...(tasks.length && {task_results}),
      bounded: Boolean(bounded && scenario.impact),
      all_hit: totals.hit + totals.body_hit, all_zero: totals.zero + totals.body_zero};
  });
  console.log(JSON.stringify({artifact: counts, scenarios: results}, null, 2));
  if (process.argv.includes('--check')) {
    const bounds = require('./bounds.json');
    for (const row of results) {
      const bound = bounds[row.capacity_gb];
      if (row.capacity_gb === 16 && row.search_bytes > 480_000_000) throw Error('16 GB search budget exceeded');
      for (const field of ['misses', 'body_misses', 'held_out_misses']) {
        const regressions = row[field].filter(query => !bound[field].includes(query));
        if (regressions.length) throw Error(row.capacity_gb + ' GB ' + field + ' regressed: ' + regressions.join(', '));
      }
      if (row.hit <= bound.hit || row.fable_hit < bound.fable_hit || row.zero > bound.zero ||
          row.fable_zero > bound.fable_zero || row.body_zero || row.misses.includes('signs of dehydration'))
        throw Error('Search quality did not meet the improvement bounds at ' + row.capacity_gb + ' GB');
      console.error(`${row.capacity_gb} GB: ${row.hit}/${row.query_count} original, ${row.body_hit}/${row.body_query_count} PDF body, ${row.held_out_hit}/${row.held_out_query_count} held out, ${row.zero} empty, no regressions.`);
    }
  }
}

benchmark(process.argv[2], process.argv[3]).catch(error => { console.error(error); process.exitCode = 1; });
