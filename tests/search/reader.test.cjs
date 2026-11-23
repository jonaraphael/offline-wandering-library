'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {reviewedGuide, reviewedGuides, emergencyDomain, emergencySource} = require('../../src/owl/templates/search.js');
const sections = require('../../catalog/emergency-sections.json');
const wikiMed = require('../../catalog/wikimed-phone/manifest.json');
const heldOut = require('./held-out-queries.json');
const everyday = require('./everyday-emergency-queries.json');
const paraphrases = require('./emergency-paraphrases.json');
const original = require('./queries.json');
const emergencySamples = require('./section-emergency-queries.json');
const semanticSamples = require('./semantic-emergency-queries.json');
const round5 = require('./round5-queries.json');
const round6 = require('./round6-queries.json');
const round7 = require('./round7-queries.json');

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

test('section routes prefer specific situations and ambiguous clues use the right domain', () => {
  const documents = new Map(Object.values(sections.sources).map(([id]) => [id, {id, href: id + '.pdf'}]));
  for (const [query, topic, page] of [
    ['His arms are jerking and his eyes rolled back', 'seizure', 22],
    ['Gran fell and her hip hurts', 'hip-fracture', 25],
    ['The toddler shoved a pea into a nostril', undefined, undefined],
    ['A wildfire evacuation order', 'wildfire', 15],
    ['A newborn has not started breathing', 'newborn-resuscitation', 20],
    ['Cut her finger and it is gaping', 'large-cuts', 11],
    ['Hypoglycaemia', 'low-blood-sugar', 32],
  ]) {
    const result = reviewedGuide(documents, query);
    assert.equal(result?.topic, topic, query);
    if (page) assert.ok(result.href.endsWith('#page=' + page), query);
  }
  for (const query of ['My friend is turning blue', 'My toddler stuffed an object in her nose', 'The old man fell and hurt his hip',
    'My dad is lying still on the ground', 'Her finger was cut by a saw', 'The jellyfish left marks on his arm']) {
    assert.equal(emergencyDomain(query), 'health', query);
  }
  for (const query of ['My dad wants to fix a four stroke engine', 'How to pressure can green beans',
    'An Old Man and the Sea audiobook', 'blood orange jam', 'flood fill algorithm', 'aircraft stall descent',
    'the ticket is stuck in the printer', 'yellow marks on a spider plant']) {
    assert.equal(emergencyDomain(query), '', query);
    assert.equal(reviewedGuide(documents, query), undefined, query);
  }
  for (const category of ['fiction', 'music', 'aviation', 'food_preservation', 'agriculture']) {
    assert.equal(emergencySource({category}, 'health'), false);
    assert.equal(emergencySource({category}, 'safety'), false);
  }
  assert.equal(emergencySource({category: 'first_aid'}, 'health'), true);
  assert.equal(emergencySource({category: 'preparedness'}, 'safety'), true);
});

test('reviewed gaps lead to the pinned condition or hazard page', () => {
  const documents = new Map(Object.values(sections.sources).map(([id]) => [id, {
    id, href: id + (id === 'wikimed_en' ? '.zim' : '.pdf'),
  }]));
  for (const [query, topic, file, locator] of [
    ['Dad has facial drooping and slurred speech', /stroke/, 'medical_bec', 139],
    ['I am throwing up blood', /gastrointestinal-bleeding/, 'msf_guideline-170-en', 122],
    ['A branch struck my eye and my vision is blurry', /injury-to-eye/, 'hesperian_en_wtnd_2025_16', 2],
    ['My kid is limp after a febrile seizure', /febrile-seizure/, 'msf_guideline-170-en', 23],
    ['His hands are tingling after swimming in cold water', /cold-water-injury/, 'cert', 114],
    ['Stabbed in the abdomen', /penetrating-wound/, 'hesperian_en_wtnd_2025_10', 16],
    ['He fell from the roof and is not moving', /fall-from-height/, 'medical_bec', 58],
    ['There is mold after the flood in our basement', /flood-mold/, 'wikimed_en', 'Mold_health_issues'],
    ['I smell smoke from inside the walls', /fire-smoke/, 'cert', 173],
    ['The river is rising and we need to leave our house', /flood-evacuation/, 'fema_are_you_ready_2020', 11],
  ]) {
    const result = reviewedGuide(documents, query);
    assert.ok(result, query);
    assert.match(result.topic, topic, query);
    assert.equal(result.id, file, query);
    if (typeof locator === 'number') assert.equal(result.href, file + '.pdf#page=' + locator, query);
    else assert.equal(result.location, 'Archive path: ' + locator, query);
  }
});

const reader = process.env.OWL_SEARCH_READER;
const negationCases = round5.emergency.filter(sample => sample.excluded);

test('reviewed routes discard negated and historical clues and keep independent active situations', () => {
  const documents = new Map(Object.values(sections.sources).map(([id]) => [id, {
    id, href: id + (id === 'wikimed_en' ? '.zim' : '.pdf'),
  }]));
  const samples = [...round5.routingGate, ...round5.emergency];
  for (const {query, topics, excluded = [], allTopics} of samples) {
    const actual = reviewedGuides(documents, query).map(guide => guide.topic);
    assert.ok(allTopics ? topics.every(topic => actual.includes(topic)) : topics.includes(actual[0]), query);
    assert.ok(excluded.every(topic => !actual.includes(topic)), query);
  }
});

test('round 6 routes distinguish contamination from drowning and keep readable emergency PDF companions', () => {
  const documents = new Map([...Object.values(sections.sources).map(([id]) => id), 'water'].map(id => [id, {
    id, href: id + (id === 'wikimed_en' ? '.zim' : '.pdf'),
  }]));
  for (const sample of round6.confusions) {
    const guides = reviewedGuides(documents, sample.query);
    assert.ok(sample.topics.includes(guides[0]?.topic), sample.query);
    assert.ok(!guides.some(guide => sample.excluded.includes(guide.topic)), sample.query);
  }
  const well = reviewedGuides(documents, 'flood water got into the well, can we drink it if we boil it');
  assert.deepEqual(well.map(guide => guide.topic), ['drinking-water']);
  assert.equal(reviewedGuide(documents, 'flood water got into our well').topic, 'drinking-water');
  assert.equal(reviewedGuide(documents, 'A child fell into the flooded well').topic, 'drowning');
  assert.equal(reviewedGuide(documents, 'Can we boil water from the well?', new Set(['wikimed_en'])), undefined);
  assert.equal(reviewedGuide(documents, 'My 82-year-old aunt was found on the ground after several hours').topic, 'long-lie');
  for (const [query, archived, page] of [
    ['toddler drank bleach', 'Poisoning', 'hesperian_en_wtnd_2025_10.pdf#page=29'],
    ['fell through ice', 'Drowning', 'cert.pdf#page=114'],
    ['swallowed a watch battery', 'Foreign_body', 'medical_bec.pdf#page=26'],
  ]) {
    const guides = reviewedGuides(documents, query);
    if (archived) {
      assert.ok(guides.some(guide => guide.location === 'Archive path: ' + archived), query);
      const scoped = reviewedGuides(documents, query, new Set(['wikimed_en']));
      assert.ok(scoped.some(guide => guide.href === page), query);
    }
    assert.ok(guides.some(guide => guide.href === page), query);
  }
  console.log('Round 6 routing: 10 confusion probes, long lie, and 3 reported readable routes passed.');
});

test('16 GB round 6 frozen emergency probes meet relevance and non-empty floors', {
  skip: !reader && 'Run scripts/search_benchmark.py --check-reader with Chromium and playwright-core.',
}, async () => {
  const {chromium} = require('playwright-core');
  const {measureRound6, searchUrl} = require('../../scripts/search_timing.cjs');
  const previous = [...heldOut, ...everyday, ...paraphrases, ...original, ...emergencySamples, ...semanticSamples]
    .map(([query]) => query).concat(round5.emergency.map(({query}) => query));
  const frozen = Object.values(round6).flat().map(({query}) => query);
  assert.deepEqual(Object.values(round6).map(samples => samples.length), [10, 10, 10]);
  assert.equal(new Set(frozen).size, 30);
  assert.ok(frozen.every(query => !previous.includes(query)));
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE_PATH});
  try {
    const grades = await measureRound6(browser, searchUrl(reader));
    assert.ok(grades.good >= 26, JSON.stringify(grades));
    assert.equal(grades.empty, 0);
  } finally {
    await browser.close();
  }
});

test('16 GB reader keeps current guides, shows excerpt credit and corrects zero-hit spelling', {
  skip: !reader && 'Run scripts/search_benchmark.py --check-reader with Chromium and playwright-core.',
}, async () => {
  const {chromium} = require('playwright-core');
  const {measure, searchUrl, grade} = require('../../scripts/search_timing.cjs');
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE_PATH});
  try {
    const url = searchUrl(reader);
    for (const sample of [...round5.routingGate, ...negationCases, ...round5.emergency.filter(row => row.allTopics)]) {
      const result = await measure(browser, url, sample.query);
      assert.ok(grade(sample, result).good, JSON.stringify(result));
      assert.ok(result.emergency);
      if (!sample.allTopics) assert.ok(sample.topics.includes(result.cards[0].topic), JSON.stringify(result));
    }
    console.log('Reader routing: both reported failures and controls, 10 new negation or history cases, and independent guides passed.');

    const credited = await measure(browser, url, 'light dependent reactions of photosynthesis');
    const passage = credited.cards.find(card => /OpenStax_concepts-biology\.pdf/i.test(card.href) && card.excerpt);
    assert.ok(passage, JSON.stringify(credited));
    assert.match(passage.credit, /Access for free at openstax\.org/i);
    assert.match(passage.credit, /CC[- ]BY/i);
    console.log('Reader attribution: visible OpenStax credit and license accompany the excerpt.');

    const sample = round5.spellingGate;
    const corrected = await measure(browser, url, sample.query);
    assert.ok(grade(sample, corrected).good, JSON.stringify(corrected));
    assert.equal(corrected.correction, 'Showing results for “diarrhea in children”.');
    console.log('Reader spelling: ' + corrected.correction + ' ' + corrected.cards[0].title);
  } finally {
    await browser.close();
  }
});

test('16 GB reader meets the frozen round 5 recall and practical-search timing floors', {
  skip: !reader && 'Run scripts/search_benchmark.py --check-reader with Chromium and playwright-core.',
}, async () => {
  const {chromium} = require('playwright-core');
  const {measure, searchUrl, measureRound5, calibrate, checkTiming, timingBounds} = require('../../scripts/search_timing.cjs');
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE_PATH});
  try {
    const url = searchUrl(reader);
    assert.equal(round5.emergency.length, 20);
    assert.equal(negationCases.length, 8);
    assert.equal(round5.practical.length, 10);
    assert.equal(round5.misspelled.length, 10);
    const calibration = await calibrate(browser, url);
    const summary = await measureRound5(browser, url);
    assert.ok(summary.good >= 34);
    assert.equal(summary.emergency_empty, 0);
    assert.equal(summary.negation_failures, 0);
    for (const group of [summary.practical, summary.misspelled]) {
      assert.equal(group.good, 10, JSON.stringify(group));
      checkTiming(group, calibration);
    }
    for (const {query, title} of round5.practicalGate) {
      const result = await measure(browser, url, query);
      assert.match(result.cards[0].title, new RegExp(title, 'iu'), JSON.stringify(result));
      if (query === 'how to can green beans') {
        assert.equal(result.cards[0].title, 'Snap and Italian Beans');
        assert.match(result.cards[0].href, /USDA_Canning_04_Vegetables_2015\.pdf#page=9$/);
      }
      checkTiming(timingBounds(result), calibration);
      console.log('Reader practical: ' + query + ' → ' + result.cards[0].title + ' (' +
        result.complete_ms + ' ms, ' + result.bytes + ' bytes, ' + result.reads + ' files).');
    }
  } finally {
    await browser.close();
  }
});

test('reader finds exact passages on a one-book drive and opens reviewed navigation pages', {
  skip: !reader && 'Run scripts/search_benchmark.py --check-reader with Chromium and playwright-core.',
}, async () => {
  const {chromium} = require('playwright-core');
  const {measureRound7, searchUrl} = require('../../scripts/search_timing.cjs');
  assert.deepEqual(Object.values(round7).map(samples => samples.length), [5, 5, 5]);
  const frozen = Object.values(round7).flat().map(({query}) => query.toLowerCase());
  const previous = [...heldOut, ...everyday, ...paraphrases, ...original, ...emergencySamples, ...semanticSamples]
    .map(([query]) => query.toLowerCase());
  for (const group of [round5, round6]) {
    previous.push(...Object.values(group).flat().map(({query}) => query.toLowerCase()));
  }
  assert.equal(new Set(frozen).size, 15);
  assert.ok(frozen.every(query => !previous.includes(query)));
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE_PATH});
  try {
    const summary = await measureRound7(browser, searchUrl(reader));
    assert.deepEqual(summary, {
      exact: {good: 5, empty: 0},
      practical: {good: 5, empty: 0},
      emergency: {good: 5, empty: 0},
    });
  } finally {
    await browser.close();
  }
});

test('16 GB offline reader meets the emergency recall floors and checks paraphrases in the first card', {
  skip: !reader && 'Run scripts/search_benchmark.py --check-reader with Chromium and playwright-core.',
}, async () => {
  const {chromium} = require('playwright-core');
  const {measure, searchUrl, emergencyFallback, semanticChecks} = require('../../scripts/search_timing.cjs');
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
        const {cards, cardCount} = await measure(browser, url, query, {allowEmpty: true});
        assert.ok(cardCount > 0, name + ' returned no cards for ' + query);
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

    const immersion = await measure(browser, url, 'My friend fell into icy water and her hands are tingling');
    assert.deepEqual(immersion.cards.map(card => card.topic), ['drowning', 'cold-water-injury', 'drowning']);
    assert.match(immersion.cards[1].href, /\/CERT_2019\.pdf#page=114$/);
    assert.match(immersion.cards[2].href, /\.pdf#page=89$/);

    const documents = new Map(Object.values(sections.sources).map(([id]) => [id,
      {id, href: id + (id === 'wikimed_en' ? '.zim' : '.pdf')}]));
    for (const [text, expected] of semanticChecks) {
      assert.equal(reviewedGuide(documents, text), undefined, text);
      assert.equal(emergencyDomain(text), '', text);
      const byMeaning = await measure(browser, url, text);
      assert.equal(byMeaning.emergency, true, text);
      assert.equal(byMeaning.cards[0]?.topic, expected, text);
    }
    console.log('Health and hazard descriptions with no lexical trigger lead with the Potion match.');

    const nearby = await measure(browser, url, emergencyFallback);
    assert.equal(nearby.emergency, true);
    assert.ok(nearby.cardCount >= 1 && nearby.cardCount <= 4);
    assert.ok(nearby.cards.every(card => (card.indexed || card.nearby) && !card.topic));
    assert.ok(nearby.chunk_reads > 0, 'the emergency fallback must attempt an index read');
    assert.equal(nearby.status, 'No reviewed guide matched. These passages may help.');
    assert.ok(nearby.cards.some(card => card.nearby === 'urgent-guides') || nearby.browse.length === 1);
    console.log('Emergency fallback: ' + nearby.cardCount + ' cards, index reads, plain label, and Browse Home link.');

    const fallback = await measure(browser, url, 'outlet left by the zephyric mailbox keeps flickering');
    assert.equal(fallback.cards[0]?.nearby, 'urgent-guides');
    assert.equal(fallback.cards[0]?.href, '#/');
    assert.match(fallback.cards[1]?.href, /\/CERT_2019\.pdf#page=175$/);
    assert.equal(fallback.status, 'No reviewed guide matched. These passages may help.');
    const neutral = await measure(browser, url, 'zxqv jsbix zephyric', {allowEmpty: true});
    assert.equal(neutral.cardCount, 0);
    assert.deepEqual(neutral.browse, [['Browse Home', '#/']]);
    console.log('Weak-result fallback: Urgent guides and an electrical safety PDF for the hazard; neutral query can be empty.');

    for (const text of ['book about art and smoke', 'prevent mosquito bites', 'how rain barrels collect water']) {
      const reference = await measure(browser, url, text, {allowEmpty: true});
      assert.equal(reference.emergency, false, text);
      assert.ok(reference.cards.every(card => !card.topic), text);
    }

    const headInjury = await measure(browser, url, 'my friend hit his head and keeps throwing up', {allowEmpty: true});
    assert.equal(headInjury.cards[0]?.topic, 'head-injury');
  } finally {
    await browser.close();
  }
});

test('16 GB section emergency queries meet top-three and non-empty floors', {
  skip: !reader && 'Run scripts/search_benchmark.py --check-reader with Chromium and playwright-core.',
}, async () => {
  const {chromium} = require('playwright-core');
  const {measure, searchUrl} = require('../../scripts/search_timing.cjs');
  const allQueries = [...emergencySamples, ...heldOut, ...everyday, ...paraphrases, ...original];
  assert.equal(emergencySamples.length, 40);
  assert.ok(new Set(emergencySamples.map(([, situation]) => situation)).size >= 25);
  assert.equal(new Set(allQueries.map(([query]) => query)).size, allQueries.length);
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE_PATH});
  const reviewedSource = /CERT_2019\.pdf|msf_guideline-(?:170|449)-en\.pdf|medical_bec|basic.emergency.care|are.you.ready|hesperian|where.there.is.no.doctor|a.book.for.midwives/i;
  const grades = {good: 0, partial: 0, poor: 0};
  const empty = [], unclassified = [];
  try {
    for (const [query, situation, expected, nearby] of emergencySamples) {
      const {cards, cardCount, emergency} = await measure(browser, searchUrl(reader), query, {allowEmpty: true});
      if (!emergency) unclassified.push(query);
      if (!cardCount) empty.push(query);
      const exact = new RegExp(expected, 'iu'), related = new RegExp(nearby, 'iu');
      const grade = cards.some(card => exact.test(card.title) &&
        (card.topic || reviewedSource.test(card.href + ' ' + card.locator))) ? 'good'
        : cards.some(card => exact.test(card.title) || related.test(card.title)) ? 'partial' : 'poor';
      grades[grade]++;
      if (grade !== 'good') console.log(JSON.stringify({situation, query, grade, titles: cards.map(card => card.title)}));
    }
  } finally {
    await browser.close();
  }
  console.log('Section emergency top 3: ' + grades.good + ' good / ' + grades.partial + ' partial / ' + grades.poor +
    ' poor, ' + empty.length + ' empty, ' + unclassified.length + ' unclassified (floors 32 good, 0 empty)');
  assert.ok(grades.good >= 32, JSON.stringify(grades));
  assert.deepEqual(empty, []);
  assert.deepEqual(unclassified, []);
});

test('16 GB unseen emergency descriptions meet top-three and non-empty floors', {
  skip: !reader && 'Run scripts/search_benchmark.py --check-reader with Chromium and playwright-core.',
}, async () => {
  const {chromium} = require('playwright-core');
  const {measure, searchUrl} = require('../../scripts/search_timing.cjs');
  const previous = [...emergencySamples, ...heldOut, ...everyday, ...paraphrases, ...original];
  const all = [...previous, ...semanticSamples];
  assert.equal(semanticSamples.length, 40);
  assert.ok(new Set(semanticSamples.map(([, situation]) => situation)).size >= 30);
  assert.equal(new Set(all.map(([query]) => query)).size, all.length);

  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE_PATH});
  const reviewedSource = /CERT_2019\.pdf|msf_guideline-(?:170|449)-en\.pdf|medical_bec|basic.emergency.care|are.you.ready|hesperian|where.there.is.no.doctor|wiki.?med/i;
  const grades = {good: 0, partial: 0, poor: 0, empty: 0};
  const unclassified = [];
  try {
    for (const [query, situation, expected, nearby] of semanticSamples) {
      const {cards, emergency} = await measure(browser, searchUrl(reader), query, {allowEmpty: true});
      if (!emergency) unclassified.push(query);
      const exact = new RegExp(expected, 'iu'), related = new RegExp(nearby, 'iu');
      const grade = !cards.length ? 'empty' : cards.some(card => exact.test(card.title) &&
        (card.topic || reviewedSource.test(card.href + ' ' + card.locator))) ? 'good'
        : cards.some(card => exact.test(card.title) || related.test(card.title)) ? 'partial' : 'poor';
      grades[grade]++;
      if (grade !== 'good') console.log(JSON.stringify({situation, query, grade, titles: cards.map(card => card.title)}));
    }
  } finally {
    await browser.close();
  }
  console.log('Unseen emergency top 3: ' + grades.good + ' good / ' + grades.partial + ' partial / ' +
    grades.poor + ' poor / ' + grades.empty + ' empty, ' + unclassified.length +
    ' unclassified (floors 34 good, 0 empty)');
  assert.ok(grades.good >= 34, JSON.stringify(grades));
  assert.equal(grades.empty, 0);
  assert.deepEqual(unclassified, []);
});
