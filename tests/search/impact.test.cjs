'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {gzipSync} = require('node:zlib');
const rank = require('../../src/owl/templates/rank.js');

test('a term bucket decodes impact bands and charges its pinned read size', async () => {
  const query = rank.prepareQuery('water', () => null);
  const word = query.query[0];
  const postings = [9, 2, 4, 7, 3, 1, 8];
  const row = Buffer.concat([Buffer.from([word.length, postings.length, 3]), Buffer.from(word), Buffer.from(postings)]);
  const packed = gzipSync(row).toString('base64');
  const block = await rank.impactBlock(packed);
  assert.deepEqual([...rank.impactPostings(block.get(word).data)], [[4, 9], [11, 9], [8, 3]]);
  const bucket = (rank.hashTerm(word) >>> 24).toString(16).padStart(2, '0') + '.js';
  const evidence = await rank.impactEvidence(query, {[bucket]: 512}, async path => {
    assert.equal(path, bucket);
    return block;
  });
  assert.equal(evidence.hits.get(11).get(word), 9);
  assert.equal(evidence.readBytes, 512);
  const overBudget = await rank.impactEvidence(query, {[bucket]: 4_000_001}, async () => {
    assert.fail('oversize bucket loaded');
  });
  assert.equal(overBudget.readBytes, 0);
});

test('posting decoder rejects zero deltas and unordered impact bands', () => {
  assert.throws(() => [...rank.impactPostings(Uint8Array.of(9, 1, 0))], /Invalid impact part address/);
  assert.throws(() => [...rank.impactPostings(Uint8Array.of(9, 1, 3, 10, 1, 1))], /Invalid impact band/);
});
