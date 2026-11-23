'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const rank = require('../../src/owl/templates/rank.js');

const noVector = () => null;
const index = (rows) => {
  const postings = Object.create(null);
  rows.forEach(([title, , lead], number) => {
    for (const word of rank.terms(lead)) (postings[word] ??= []).push(number * 16 + 3);
    for (const word of rank.terms(title)) {
      const posts = postings[word] ??= [];
      if (posts.length && posts.at(-1) >>> 4 === number) posts.pop();
      posts.push(number * 16 + 9);
    }
  });
  return {records: rows, postings, vectors: []};
};

test('intent wrappers remove filler while keeping the topic and audience preference', () => {
  const query = rank.prepareQuery('How can I use fractions for kids, explained simply?', noVector);
  assert.deepEqual(query.query, ['fraction']);
  assert.equal(query.audience, true);
  assert.equal(rank.prepareQuery('simple machines', noVector).phrase, 'simple machines');
});

test('beginner arithmetic favors accessible references', () => {
  const query = rank.prepareQuery('Division explained simply for kids', noVector);
  const hits = rank.rankPart(index([
    ['Polynomial long division', 4, 'Division of two polynomials', '', 0, 0],
    ['Elementary arithmetic: division', 15, 'Division of whole numbers', '', 0, 0],
  ]), query, {title: 'Mathematics', format: 'pdf'}, 2);
  assert.deepEqual(hits.map(hit => hit.row[1]), [15, 4]);
});

test('lay emergency terminology routes to relevant clinical references', () => {
  const query = rank.prepareQuery('They are losing too much blood', noVector);
  assert.equal(query.emergency, true);
  assert.ok(query.routing.includes('hemorrhag'));
  const title = index([['External hemorrhage', 9, '', '', 0, 0]]);
  const relevant = rank.rankPart(title, query, {format: 'pdf', critical: true, category: 'medical', title: 'First Aid'}, 3)[0];
  const unrelated = rank.rankPart(title, query, {format: 'pdf', critical: true, category: 'science', title: 'Engineering'}, 3)[0];
  assert.equal(relevant.focused, true);
  assert.ok(relevant.score > unrelated.score);
  assert.equal(rank.prepareQuery('bleed a radiator', noVector).emergency, false);
});

test('dehydration assessment favors a dedicated reference over passing mentions', () => {
  const query = rank.prepareQuery('What are the symptoms of dehydration?', noVector);
  const mentions = index([['Assessment of shock', 5, 'Check for signs of dehydration, bleeding and infection.', '', 0, 0]]);
  const dedicated = index([['Dehydration', 'Dehydration', '', '', 0, 0]]);
  const general = rank.rankPart(mentions, query,
    {title: 'First Aid', category: 'medical', critical: true, format: 'pdf'}, 1)[0];
  const reference = rank.rankPart(dedicated, query, {title: 'Health reference', format: 'zim'}, 1)[0];
  assert.equal(reference.focused, true);
  assert.ok(reference.score > general.score);
});

test('leftover and shelter queries rank guides by their treatment of the topic', () => {
  const source = {title: 'Reference', format: 'zim'};
  for (const [text, title, distractor] of [
    ['What temperature should I use to reheat leftovers?', 'Reheating leftovers', 'Operating temperature'],
    ['How can I ventilate a small tent?', 'Natural ventilation', 'Emergency shelter'],
  ]) {
    const part = index([[distractor, 'other', text, '', 0, 0], [title, 'guide', title, '', 0, 0]]);
    assert.equal(rank.rankPart(part, rank.prepareQuery(text, noVector), source, 2)[0].row[0], title);
  }
});

test('only a marked, matching answer clears the discussion penalty', () => {
  const query = rank.prepareQuery('solder copper wire', noVector);
  const article = ['Solder copper wire', 'sample', 'Solder the copper wire', '', 0, 0];
  const discussion = {id: 'sample', title: 'Q&A', format: 'zim', discussion: true};
  const old = rank.rankPart(index([article]), query, discussion, 1)[0];
  const answer = rank.rankPart(index([[...article, 1]]), query, discussion, 1)[0];
  const unrelated = rank.rankPart(index([[article[0], article[1], 'Place the battery on the table', '', 0, 0, 1]]), query, discussion, 1)[0];
  const guide = rank.rankPart(index([['Copper wire joints', 2, 'Solder the copper wire', '', 0, 0]]), query,
    {id: 'guide', title: 'Electrical Repair', format: 'pdf'}, 1)[0];
  assert.ok(guide.score > old.score);
  assert.equal(old.score, unrelated.score);
  assert.ok(answer.score > old.score);
});

test('focused indexed results are shown before exact catalog titles', () => {
  const make = (href, options) => ({record: {href, location: ''}, ...options});
  const exact = make('CATALOG.html', {score: 100000});
  const ordinary = make('ordinary.pdf', {});
  const focused = make('first-aid.pdf', {focused: true});
  assert.equal(rank.mergeRanked([ordinary], [exact])[0], exact);
  assert.equal(rank.mergeRanked([focused], [exact])[0], focused);
});

test('child symptoms favor pediatric references and childbirth still favors delivery guidance', () => {
  const source = {id: 'health', title: 'Community Health', format: 'pdf', category: 'medical', critical: true};
  const passages = index([
    ['The birth of the placenta: stage 3 of labor', 4, 'Causes of fever in a newborn during birth', '', 0, 0],
    ['The sick newborn', 9, 'Causes of fever in a newborn', '', 0, 0],
  ]);
  const illness = rank.prepareQuery('Fever in a newborn', noVector);
  assert.equal(illness.pediatricHealth, true);
  assert.equal(rank.rankPart(passages, illness, source, 3)[0].row[1], 9);
  const mixed = index([
    ['Page 4', 4, 'Stages of labor. Fever and dehydration in a newborn.', '', 0, 0],
    ['Page 9', 9, 'Fever and dehydration in a newborn.', '', 0, 0],
  ]);
  assert.equal(rank.rankPart(mixed, illness, source, 3)[0].row[1], 9);
  assert.equal(rank.prepareQuery('Explain fevers for children', noVector).pediatricHealth, false);
  const vomiting = rank.prepareQuery('An infant cannot keep water down and is throwing up', noVector);
  assert.ok(vomiting.emergency && vomiting.pediatricHealth && vomiting.routing.includes('dehydration'));
  const delivery = rank.prepareQuery('Deliver a baby at home', noVector);
  assert.equal(delivery.deliveryQuery, true);
  assert.equal(delivery.pediatricHealth, false);
});

test('compact semantic candidates can match without a shared literal term', () => {
  const direction = new Array(256).fill(1);
  const near = Buffer.alloc(32, 255).toString('base64');
  const far = Buffer.alloc(32).toString('base64');
  const prepared = rank.prepareQuery('Patch a coat', () => rank.binaryQuery(direction));
  const part = {...index([['Mending garments', 1, '', near, 0, 0],
                           ['Output voltage', 2, '', far, 0, 0]]), semantic: [0, 1]};
  const hits = rank.rankPart(part, prepared, {format: 'pdf', title: 'Manual'}, 3);
  assert.deepEqual(hits.map(hit => hit.row[1]), [1]);
});

test('language requests distinguish phrasebooks from unrelated language mentions', () => {
  const entries = index([
    ['Traditional Portuguese markets', 3, 'Portuguese dining and common market phrases', '', 0, 0],
    ['Portuguese phrasebook', 9, 'A conversation for paying at the counter', '', 0, 0],
  ]);
  const query = rank.prepareQuery('How do I ask for a receipt in Portuguese?', noVector);
  assert.equal(query.language, 'portuguese');
  assert.equal(rank.rankPart(entries, query, {title: 'Travel', format: 'pdf'}, 3)[0].row[1], 9);
  assert.equal(rank.prepareQuery('History of the Portuguese empire', noVector).language, false);
});

test('cloth and garment queries route to sewing vocabulary', () => {
  const sewing = rank.prepareQuery('How do I join fabric by hand?', noVector);
  const mending = rank.prepareQuery('What do I use to patch torn socks?', noVector);
  assert.ok(sewing.routing.includes('sewing'));
  assert.ok(mending.routing.includes('darn'));
  assert.equal(rank.prepareQuery('How do I stitch a wound?', noVector).routing.includes('sewing'), false);
});

test('restricted passage labels retain the book and section with the physical page locator', () => {
  const asset = {id: 'example', restricted: true, format: 'pdf', title: 'Medical guide — 2 Child health',
    destination: 'HEALTH/basics.pdf', entrypoints: [[1, 'Assessment · Page 1']]};
  const hit = rank.result(asset, {row: ['Page 3', 3, ''], index: 1}, 0).record;
  assert.equal(hit.title, 'Medical guide — 2 Child health · Assessment · Page 3');
  assert.equal(hit.href, 'HEALTH/basics.pdf#page=3');
  assert.equal(hit.description, '');
});

test('legacy placeholder titles retain a reference label and the physical locator', () => {
  const asset = {id: 'cd3wd', title: 'Appropriate development library', format: 'zim',
    destination: 'ZIM/cd3wd.zim', title_overrides: {'documents/B990_20.HTM': 'How does breastfeeding work?'}};
  const title = (raw, locator) => rank.result(asset, {row: [raw, locator, ''], index: 0}, 0).record;
  assert.deepEqual([title('B990 20.HTM', 'documents/B990_20.HTM').title,
    title('B990 20.HTM', 'documents/B990_20.HTM').location],
  ['How does breastfeeding work?', 'Archive path: documents/B990_20.HTM']);
  for (const raw of ['', '235', 'Page 6', '../archive/readme', 'B541 3.HTM']) {
    assert.ok(rank.placeholderTitle(raw), raw);
    assert.ok(!rank.placeholderTitle(title(raw, 'other').title), raw);
  }
});

test('term dictionaries route title-only postings without opening unrelated record chunks', async () => {
  const {mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync} = require('node:fs');
  const {tmpdir} = require('node:os');
  const {join} = require('node:path');
  const {gzipSync} = require('node:zlib');
  const compiler = require('../../scripts/build_query_index.cjs');
  const queryIndex = require('../../src/owl/templates/query-index.js');
  const temp = mkdtempSync(join(tmpdir(), 'owl-query-index-'));
  const digest = 'a'.repeat(64);
  const partDirectory = join(temp, 'sources', digest);
  const titles = ['Bearing_parts', 'Hand_loom'];
  const asset = {id: 'fixture', title: 'Repair handbook', format: 'zim', sha256: digest, shelves: [],
    destination: 'ZIM/fixture.zim', parts: titles.map(() => ({bloom: '/w==', bytes: 300}))};
  try {
    mkdirSync(partDirectory, {recursive: true});
    const packed = titles.map((title, n) => {
      const body = {records: [[null, title, '', '', 0, 1]], postings: {}};
      const encoded = gzipSync(JSON.stringify(body)).toString('base64');
      writeFileSync(join(partDirectory, '0000' + n + '.js'), 'globalThis.OWLShardPart(' +
        JSON.stringify([digest, n, encoded]) + ');\n');
      return encoded;
    });
    const output = join(temp, 'query');
    compiler.compile({sources: [asset]}, temp, output, join(temp, 'work'));
    const read = async name => {
      const script = readFileSync(join(output, name), 'utf8');
      return JSON.parse(script.slice('globalThis.OWLQueryBlock('.length, -3));
    };
    const layout = await read('index.js');
    const files = [];
    const hits = await queryIndex.search(layout, read, {sources: [asset]}, noVector,
      async (_digest, part, terms) => {
        files.push(part);
        return rank.unpack(packed[part], terms);
      }, 'bearing');
    assert.deepEqual(files, [0]);
    assert.equal(hits[0].record.title, 'Bearing parts');
    assert.equal(hits[0].record.location, 'Archive path: Bearing_parts');
  } finally {
    rmSync(temp, {recursive: true, force: true});
  }
});
test('indexed ranking stays within its requested allowance and cancels between chunks', async () => {
  const path = n => 'chunks/' + String(n).padStart(64, '0') + '.js';
  const parts = [0, 1, 2].map(n => ({path: path(n), bloom: '/w==', bytes: 10, number: n}));
  const selection = {sources: [{id: 'manual', title: 'Manual', format: 'pdf', sha256: 'a'.repeat(64),
    href: 'Manual.pdf', destination: 'Manual.pdf', parts}]};
  const chunks = [
    index([['Workshop supplies', 1, 'A guide to flat bicycle tires', '', 0, 0]]),
    index([['Patching a Bicycle Tire Inner Tube', 2, 'Replace or patch a puncture', '', 0, 0]]),
    index([['Repairing a handlebar', 3, 'For a bicycle', '', 0, 0]])
  ];
  const reads = [], progress = [];
  const readPart = (_digest, number) => {
    reads.push(number);
    return chunks[number];
  };
  const query = 'How do I fix a flat bicycle tire?';
  const completed = await rank.search(selection, noVector, readPart, query, 'all', 3,
    () => false, hits => progress.push(...hits), 10, undefined, true);
  assert.deepEqual(reads, [0]);
  assert.equal(progress[0].record.location, 'Page 1');
  assert.equal(completed[0].record.location, 'Page 1');
  assert.equal((await rank.search(selection, noVector, readPart, query, 'all', 3))[0].record.location, 'Page 2');
  reads.length = 0;
  let cancelled = false;
  const abandoned = await rank.search(selection, noVector, readPart, query, 'all', 3,
    () => cancelled, () => { cancelled = true; }, 30, undefined, true);
  assert.deepEqual(abandoned, []);
  assert.deepEqual(reads, [0]);
});

test('ordinary and emergency searches stay bounded across selection sizes and term index availability', async () => {
  const parts = [0, 1, 2].map(n => ({number: n, bloom: '/w==', bytes: 7_000_000}));
  const asset = {id: 'manual', title: 'Manual', format: 'pdf', sha256: 'a'.repeat(64),
    destination: 'Manual.pdf', parts};
  const content = index([['Dehydration', 3, 'Treatment with oral rehydration', '', 0, 0]]);
  const reads = [];
  const readPart = (_digest, number) => { reads.push(number); return content; };
  const readImpact = () => assert.fail('No buckets in the fixture');
  const run = (selection, text) => rank.search(selection, noVector, readPart, text, 'all', 5,
    () => false, undefined, rank.boundedBytes, readImpact, true);
  await run({sources: [asset], impact: {}}, 'signs of dehydration');
  assert.deepEqual(reads, [0, 1]);
  reads.length = 0;
  await run({sources: [asset], impact: {}}, 'rehydration');
  assert.deepEqual(reads, [0, 1]);
  reads.length = 0;
  await run({sources: [asset], impact: undefined}, 'signs of dehydration');
  assert.deepEqual(reads, [0, 1]);
  const large = {...asset, parts: [...parts, {number: 3, bloom: '/w==', bytes: 125_000_000}]};
  reads.length = 0;
  await run({sources: [large], impact: {}}, 'rehydration');
  assert.deepEqual(reads, [0, 1, 2]);
});

test('a repair guide with the requested object in its title outranks a body mention', () => {
  const query = rank.prepareQuery('Fix a bicycle inner tube');
  const part = index([
    ['Bathing and washing', 1, 'Use a bicycle inner tube to fix the chair.'],
    ['Patching a Bicycle Tire Inner Tube', 2, 'Troubleshoot tire punctures.'],
  ]);
  const hits = rank.rankPart(part, query, {title: 'Repair guides', format: 'pdf'}, 2);
  assert.equal(hits[0].row[1], 2);
  assert.ok(hits[0].titleMatch > hits[1].titleMatch);
});

test('recipe table headings distinguish similar foods on numbered PDF pages', () => {
  const query = rank.prepareQuery('How to can green beans');
  const part = index([
    ['Page 8', 8, 'Recommended process time for Lima Beans in a dial-gauge pressure canner.'],
    ['Page 9', 9, 'Recommended process time for Snap and Italian Beans in a dial-gauge pressure canner.'],
  ]);
  const asset = {id: 'vegetables', title: 'Canning: 04. Vegetables', format: 'pdf',
    destination: 'Vegetables.pdf', category: 'food'};
  const [best] = rank.rankPart(part, query, asset, 2);
  const result = rank.result(asset, best, 0).record;
  assert.equal(result.title, 'Snap and Italian Beans');
  assert.equal(result.href, 'Vegetables.pdf#page=9');
});

test('one-edit correction needs a corresponding indexed term and keeps known words', async () => {
  const vocabulary = new Set(['diarrhea', 'diary', 'children', 'frostbite']);
  const bucket = word => (rank.hashTerm(word) >>> 24).toString(16).padStart(2, '0') + '.js';
  const indexed = new Map([
    [bucket('diarrhea'), new Map([['diarrhea', {df: 20}]])],
    [bucket('frostbit'), new Map([['frostbit', {df: 4}]])],
  ]);
  const impact = Object.fromEntries([...indexed.keys()].map(name => [name, 200]));
  const correct = text => rank.correctSpelling(text, vocabulary, impact, name => indexed.get(name), () => false);
  assert.equal(await correct('diarhea in children'), 'diarrhea in children');
  assert.equal(await correct('forstbite'), 'frostbite');
  assert.equal(await correct('diarrhea in children'), undefined);
  assert.equal(await correct('randomword'), undefined);
});

test('the lexical preview precedes model loading and shares its chunk with final ranking', {timeout: 1000}, async () => {
  const asset = {id: 'manual', title: 'Manual', format: 'pdf', sha256: 'a'.repeat(64),
    destination: 'Manual.pdf', parts: [{bloom: '/w==', bytes: 50_000}]};
  const content = index([['Dehydration', 3, 'Oral rehydration', '', 0, 0]]);
  let finishModel, showPreview, reads = 0;
  const model = new Promise(resolve => { finishModel = resolve; });
  const preview = new Promise(resolve => { showPreview = resolve; });
  const completed = rank.search({sources: [asset], impact: {}}, model, () => { reads++; return content; },
    'signs of dehydration', 'all', 3, () => false, showPreview, rank.boundedBytes, () => null, true);
  assert.equal((await preview)[0].record.location, 'Page 3');
  finishModel(noVector);
  assert.equal((await completed)[0].record.location, 'Page 3');
  assert.equal(reads, 1);
});

test('query-filtered unpacking retains accented, inflected and concept-only archive titles', async () => {
  const {gzipSync} = require('node:zlib');
  const payload = {records: [
    [null, 'other/Bérries_and_nuts', '', '', 0, 1],
    [null, 'berries/Unrelated_entry', '', '', 0, 1],
    [null, 'other/Foraging', '', '', 0, 1],
  ], postings: {berry: [37]}};
  const packed = gzipSync(JSON.stringify(payload)).toString('base64');
  const query = rank.prepareQuery('berry', noVector);
  const asset = {title: 'Reference', format: 'zim'};
  const full = rank.rankPart(await rank.unpack(packed), query, asset, 5);
  const filtered = rank.rankPart(await rank.unpack(packed, rank.lookupTerms(query)), query, asset, 5);
  assert.deepEqual(filtered, full);
  assert.deepEqual(filtered.map(hit => hit.row[0]), ['Bérries and nuts', 'Foraging']);
});

test('concept matches favor explanations over unrelated titles sharing words', () => {
  const source = {title: 'Reference', format: 'zim'};
  const cases = [
    ['what causes the seasons', 'Season', 'Atlantic hurricane season', 'Tilt of the Earth'],
    ['how does a car engine work', 'Internal combustion engine', 'Sports car engine output', 'The four-stroke engine'],
    ['how do I fix a flat bicycle tire', 'Patching a Bicycle Tire Inner Tube', 'What epistemology studies', 'Bicycle puncture'],
  ];
  for (const [query, direct, distractor, lead] of cases) {
    const records = index([[distractor, 'a', query, '', 0, 0], [direct, 'b', lead, '', 0, 0]]);
    assert.equal(rank.rankPart(records, rank.prepareQuery(query, noVector), source, 2)[0].row[0], direct);
  }
  assert.equal(rank.prepareQuery('how to help a woman give birth', noVector).deliveryQuery, true);
});
