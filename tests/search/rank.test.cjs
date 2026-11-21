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
