'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {reviewedGuide} = require('../../src/owl/templates/search.js');
const wikiMed = require('../../catalog/wikimed-phone/manifest.json');
const heldOut = require('./held-out-queries.json');
const everyday = require('./everyday-emergency-queries.json');
const paraphrases = require('./emergency-paraphrases.json');
const original = require('./queries.json');

test('reviewed routes distinguish similar emergencies and respect selected guide availability', () => {
  const documents = new Map([
    ['cert', {href: 'guide.pdf'}],
    ['medical_bec', {href: 'emergency.pdf'}],
    ['msf_guideline-170-en', {href: 'clinical.pdf'}],
    ['hesperian_en_wtnd_2025_10', {href: 'first-aid.pdf'}],
    ['hesperian_en_midw_2026_13', {href: 'birth.pdf'}],
    ['water', {href: 'water.pdf'}],
    ['wikimed_en', {href: 'medical.zim'}],
  ]);
  const articlePaths = new Set(wikiMed.volumes.flatMap(volume => volume.articles).map(article => article.path));
  for (const [query, topic, destination] of [
    ['sparks from the extension socket and a little smoke', 'electrical-fire', 'guide.pdf#page=175'],
    ['she got shocked by a frayed cable', 'electric-shock', 'Electrical_injury'],
    ['food wedged in throat and he cannot breathe', 'choking', 'emergency.pdf#page=155'],
    ['throat feels tight after a sting', 'anaphylaxis', 'clinical.pdf#page=14'],
    ['she is bleeding badly after having a baby', 'postpartum', 'birth.pdf#page=3'],
    ['he stopped breathing after we pulled him out of the lake', 'drowning', 'Drowning'],
    ['She fell into the pond and is trapped under the dock', 'drowning', 'Drowning'],
    ['He passed out but he is still breathing', 'unresponsive', 'first-aid.pdf#page=4'],
    ['She fainted and is not breathing', 'resuscitation', 'Cardiopulmonary_resuscitation'],
    ['Can I drink out of the stream?', 'drinking-water', 'water.pdf#page=1'],
    ['I think my child swallowed a small plastic toy', 'swallowed-object', 'Foreign_body'],
    ['He choked on a coin and cannot speak', 'choking', 'emergency.pdf#page=155'],
    ['My kid stepped on a rusty nail', 'puncture-wound', 'first-aid.pdf#page=15'],
    ['wasp stung me on the wrist', 'insect-sting', 'Arthropod_bites_and_stings'],
  ]) {
    const result = reviewedGuide(documents, query);
    assert.equal(result?.topic, topic, query);
    if (result.kind === 'article') {
      assert.ok(articlePaths.has(destination), destination);
      assert.equal(result.location, 'Archive path: ' + destination);
    } else assert.equal(result.href, destination);
  }
  for (const query of ['four stroke engine', 'cut a dovetail joint', 'how to use a gas stove', 'book about art and smoke',
    'changing a battery in a toy', 'she ate a quarter of the sandwich',
    'how to paddle a canoe on a lake', 'drive nails into a plank']) {
    assert.equal(reviewedGuide(documents, query), undefined, query);
  }
  assert.equal(reviewedGuide(new Map(), 'choking'), undefined);
  assert.equal(reviewedGuide(documents, 'choking', new Set(['cert'])), undefined);
  assert.equal(reviewedGuide(documents, 'choking', new Set(['medical_bec'])).topic, 'choking');
});

const reader = process.env.OWL_SEARCH_READER;
test('16 GB offline reader meets the emergency recall floors and checks paraphrases in the first card', {
  skip: !reader && 'Run scripts/search_benchmark.py --check-reader with Chromium and playwright-core.',
}, async () => {
  const {chromium} = require('playwright-core');
  const {measure, searchUrl} = require('../../scripts/search_timing.cjs');
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE_PATH});
  try {
    const url = searchUrl(reader);
    assert.equal(heldOut.length, 10);
    assert.equal(everyday.length, 30);
    assert.equal(paraphrases.length, 15);
    assert.equal(new Set([...heldOut, ...everyday, ...paraphrases, ...original].map(([query]) => query)).size, 155);
    const failures = [];
    for (const [name, samples, floor, firstReviewed] of [
      ['Existing held-out top 3', heldOut, 8, false],
      ['Everyday emergency top 3', everyday, 24, false],
      ['Emergency paraphrases first reviewed card', paraphrases, 15, true],
    ]) {
      const misses = [];
      for (const [query, expected] of samples) {
        const {cards} = await measure(browser, url, query, {allowEmpty: true});
        const pattern = new RegExp(expected, 'iu');
        const matches = firstReviewed
          ? cards[0]?.topic && pattern.test(cards[0].title)
          : cards.some(card => pattern.test(card.title));
        if (!matches) {
          misses.push({query, titles: cards.map(card => card.title)});
        }
      }
      const line = name + ': ' + (samples.length - misses.length) + '/' + samples.length + ' (floor ' + floor + ')';
      console.log(line);
      for (const miss of misses) console.log(JSON.stringify(miss));
      if (samples.length - misses.length < floor) failures.push(line);
    }
    assert.deepEqual(failures, []);

    const outlet = await measure(browser, url, 'my outlet is smoking');
    assert.equal(outlet.cards[0].topic, 'electrical-fire');
    assert.match(outlet.cards[0].href, /\/CERT_2019\.pdf#page=175$/);
    const animal = await measure(browser, url, 'a dog bit my hand');
    assert.equal(animal.cards[0].topic, 'animal-bite');
    assert.match(animal.cards[0].href, /\/msf_guideline-170-en\.pdf#page=258$/);
    console.log('Smoking outlet and dog bite: both lead with the reviewed guide.');

    const nearby = await measure(browser, url, 'what is the danger after a blow to the head and repeated vomiting');
    assert.ok(nearby.cardCount >= 1 && nearby.cardCount <= 3);
    assert.ok(nearby.cards.every(card => card.indexed && !card.topic));
    assert.ok(nearby.cards.some(card => /vomiting/i.test(card.title)));
    assert.equal(nearby.status, 'No reviewed guide matched. These passages may help.');
    assert.deepEqual(nearby.browse, [['Browse Home', '#/']]);
    console.log('Passage fallback: ' + nearby.cardCount + ' indexed cards, plain label, and Browse Home link.');

    const fallback = await measure(browser, url, 'outlet left by the zephyric mailbox keeps flickering', {allowEmpty: true});
    assert.deepEqual(fallback.cards, []);
    assert.equal(fallback.status, 'No close match. Browse Urgent guides and categories on Home.');
    assert.deepEqual(fallback.browse, [['Browse Home', '#/']]);
    console.log('Weak-result fallback: no displayed cards and Browse Home link.');

    const headInjury = await measure(browser, url, 'my friend hit his head and keeps throwing up', {allowEmpty: true});
    assert.ok(headInjury.cards.every(card => !/Traditional processing/i.test(card.title)));
  } finally {
    await browser.close();
  }
});
