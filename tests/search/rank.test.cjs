'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const rank = require('../../src/owl/templates/rank.js');
const catalog = require('../../src/owl/templates/search.js');

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
  assert.equal(catalog.mergeRanked([ordinary], [exact])[0], exact);
  assert.equal(catalog.mergeRanked([focused], [exact])[0], focused);
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
