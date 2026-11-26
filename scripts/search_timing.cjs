#!/usr/bin/env node
/* Time the shipped reader from a local file in offline, CPU-throttled Chromium. */
'use strict';
const {parseArgs} = require('node:util');
const assert = require('node:assert/strict');
const {readdirSync, statSync} = require('node:fs');
const {dirname, join, resolve} = require('node:path');
const {fileURLToPath, pathToFileURL} = require('node:url');
const {chromium} = require('playwright-core');
const round5 = require('../tests/search/round5-queries.json');
const round6 = require('../tests/search/round6-queries.json');
const round7 = require('../tests/search/round7-queries.json');

const emergencyFallback = "My neighbor is lying still on the floor and I can't tell if he's breathing";
const semanticChecks = new Map([
  ['After a twelve hour bus ride my left calf is warm and painfully swollen', 'deep-vein-thrombosis'],
  ['The downstairs stayed wet for days after the rain and now the walls are fuzzy and musty', 'flood-mold'],
]);
const emergencyQueries = [
  'signs of dehydration',
  'chest compressions',
  'snake bite',
  'make water safe to drink',
  'we are stuck outside overnight in heavy rain without a tent',
  emergencyFallback,
  ...semanticChecks.keys(),
];

async function withOfflineReader(browser, url, run) {
  const context = await browser.newContext({offline: true});
  try {
    const page = await context.newPage();
    const session = await context.newCDPSession(page);
    await session.send('Network.enable');
    await session.send('Network.setCacheDisabled', {cacheDisabled: true});
    await session.send('Emulation.setCPUThrottlingRate', {rate: 4});
    await page.goto(url);
    await page.waitForFunction(() => window.OWLShardRank && document.querySelector('#search-status')?.hidden &&
      !window.OWLShardSelection && !window.OWLShardModel);
    return await run(page);
  } finally {
    await context.close();
  }
}

async function measure(browser, url, query, {allowEmpty = false, rankedReviewed = false} = {}) {
  return withOfflineReader(browser, url, async page => {
    const reads = [];
    const failures = [];
    page.on('request', request => reads.push(new URL(request.url())));
    page.on('requestfailed', request => failures.push(request.url()));
    await page.evaluate(text => {
      const form = document.querySelector('#query').form;
      const results = document.querySelector('#search-results');
      const status = document.querySelector('#search-status');
      const started = performance.now();
      const sample = window.searchTiming = {};
      const observer = new MutationObserver(() => {
        if (sample.first === undefined && results.querySelector('[data-indexed="true"], [data-reviewed], [data-nearby]')) {
          sample.first = performance.now() - started;
        }
        if (results.dataset.searchScope === 'complete' && !status.hidden) {
          sample.complete = performance.now() - started;
          sample.status = status.textContent;
          sample.emergency = results.dataset.emergency === 'true';
          observer.disconnect();
        } else if (!status.hidden && !/^(?:Searching|Still looking)/.test(status.textContent)) {
          sample.error = status.textContent;
          observer.disconnect();
        }
      });
      observer.observe(results, {childList: true, attributes: true});
      observer.observe(status, {childList: true, attributes: true});
      form.querySelector('#query').value = text;
      form.requestSubmit();
    }, query);
    await page.waitForFunction(() => window.searchTiming.complete !== undefined || window.searchTiming.error,
      undefined, {timeout: 180_000});
    const {first, complete, status, emergency, error} = await page.evaluate(() => window.searchTiming);
    const remote = reads.filter(url => !['file:', 'blob:'].includes(url.protocol));
    if (error || failures.length || remote.length) {
      throw Error(error || 'Search requested unavailable files: ' + [...failures, ...remote].join(', '));
    }
    if (!allowEmpty && first === undefined) {
      throw Error('Search did not display an indexed or emergency guide result for: ' + query);
    }
    const {cards, cardCount} = await page.locator('#search-results article.result:visible').evaluateAll((elements, ranked) => {
      if (ranked) {
        // Grade the original reviewed-guide order even when Open requires folder access.
        elements.sort((a, b) => {
          if (a.dataset.reviewRank === undefined || b.dataset.reviewRank === undefined) return 0;
          return Number(a.dataset.reviewRank) - Number(b.dataset.reviewRank);
        });
      }
      return {cardCount: elements.length, cards: elements.slice(0, 3).map(card => ({
        title: card.querySelector('h3').textContent,
        topic: card.dataset.reviewed,
        nearby: card.dataset.nearby,
        indexed: card.dataset.indexed === 'true',
        href: card.querySelector('a.button').getAttribute('href'),
        locator: card.querySelector('small')?.textContent,
        excerpt: card.querySelector('.text')?.textContent,
        credit: card.querySelector('.attribution')?.textContent,
      }))};
    }, rankedReviewed);
    if (!allowEmpty && !cardCount) throw Error('Search finished without a result card for: ' + query);
    const correction = await page.locator('.search-correction:visible').allTextContents();
    const browse = await page.locator('#search-results > a.button:visible').evaluateAll(elements =>
      elements.map(link => [link.textContent, link.getAttribute('href')]));
    const paths = reads.filter(url => url.protocol === 'file:').map(url => fileURLToPath(url));
    return {query, first_ms: first === undefined ? null : Math.round(first * 10) / 10,
      complete_ms: Math.round(complete * 10) / 10,
      bytes: paths.reduce((sum, path) => sum + statSync(path).size, 0), reads: paths.length,
      chunk_reads: paths.filter(path => /[\\/]SEARCH[\\/](?:chunks|sources)[\\/]/.test(path)).length,
      emergency, status, correction: correction[0], cards, cardCount, browse};
  });
}

async function calibrate(browser, url) {
  // Read and unpack a fixed sample from the installed selection with the
  // same file: loading, offline context and CPU throttle as each query.
  const sourceRoot = join(dirname(fileURLToPath(url)), 'LIBRARY', 'SEARCH', 'sources');
  const files = readdirSync(sourceRoot, {recursive: true}).filter(name => /^[a-f0-9]{64}[\\/]\d{5}\.js$/.test(name))
    .sort().map(name => ({name, size: statSync(join(sourceRoot, name)).size}))
    .filter(({size}) => size >= 80_000 && size <= 220_000).slice(0, 96);
  assert.equal(files.length, 96, 'Expected 96 calibration chunks in the 16 GB selection');
  const ms = await withOfflineReader(browser, url, page => page.evaluate(async paths => {
    const terms = window.OWLShardRank.terms('contour lines on a topographic map');
    const started = performance.now();
    try {
      for (const path of paths) {
        let data;
        window.OWLShardPart = part => { data = part[2]; };
        await window.OWLDiscovery.script('SEARCH/sources/' + path);
        await window.OWLShardRank.unpack(data, terms);
      }
    } finally {
      delete window.OWLShardPart;
    }
    return performance.now() - started;
  }, files.map(({name}) => name.replace(/\\/g, '/'))));
  const msRounded = Math.round(ms * 10) / 10;
  const calibration = {ms: msRounded, reads: files.length, bytes: files.reduce((total, {size}) => total + size, 0)};
  console.log('Reader calibration: ' + JSON.stringify(calibration));
  return calibration;
}

function checkTiming(result, calibration) {
  assert.ok(result.max_bytes <= 20_000_000, JSON.stringify(result));
  assert.ok(result.max_reads <= 200, JSON.stringify(result));
  assert.ok(result.max_first_ms <= 1.75 * calibration.ms, JSON.stringify({result, calibration}));
  assert.ok(result.max_complete_ms <= 2.5 * calibration.ms, JSON.stringify({result, calibration}));
  if (process.env.OWL_SEARCH_LOCAL_TIMING === '1') {
    assert.ok(result.max_complete_ms <= 3000, JSON.stringify(result));
  }
}

function timingBounds(result) {
  return {
    max_first_ms: result.first_ms ?? Infinity,
    max_complete_ms: result.complete_ms,
    max_bytes: result.bytes,
    max_reads: result.reads,
  };
}

function grade(sample, result) {
  const topics = result.cards.map(card => card.topic);
  const excluded = sample.excluded?.some(topic => topics.includes(topic)) ?? false;
  const expected = sample.topics?.filter(topic => topics.includes(topic));
  const good = expected ? !excluded && (sample.allTopics ? expected.length === sample.topics.length : expected.length > 0) :
    result.cards.some(card => new RegExp(sample.title, 'iu').test(card.title));
  return {good, negationFailure: Boolean(sample.excluded && !good)};
}

async function measureRound5(browser, url) {
  const summary = {good: 0, emergency_empty: 0, negation_failures: 0};
  for (const group of ['emergency', 'practical', 'misspelled']) {
    const totals = summary[group] = {queries: round5[group].length, good: 0, empty: 0,
      max_first_ms: 0, max_complete_ms: 0, max_bytes: 0, max_reads: 0};
    for (const sample of round5[group]) {
      const result = await measure(browser, url, sample.query, {allowEmpty: true});
      const {good, negationFailure} = grade(sample, result);
      totals.good += Number(good);
      totals.empty += Number(!result.cardCount);
      for (const [key, value] of Object.entries(timingBounds(result))) totals[key] = Math.max(totals[key], value);
      summary.negation_failures += Number(negationFailure);
      console.log(JSON.stringify({group, good, ...result}));
    }
    summary.good += totals.good;
  }
  summary.emergency_empty = summary.emergency.empty;
  console.log(JSON.stringify(summary));
  return summary;
}

async function measureRound6(browser, url) {
  const grades = {good: 0, partial: 0, poor: 0, empty: 0};
  const groups = {};
  for (const [group, samples] of Object.entries(round6)) {
    const totals = groups[group] = {good: 0, partial: 0, poor: 0, empty: 0};
    for (const sample of samples) {
      const result = await measure(browser, url, sample.query, {allowEmpty: true});
      const matching = result.cards.filter(card => sample.topics.includes(card.topic));
      const excluded = result.cards.some(card => sample.excluded?.includes(card.topic));
      const readable = matching.some(card => /\.pdf#page=\d+$/i.test(card.href));
      const good = matching.length && !excluded && (group !== 'readable' || readable);
      const rating = !result.cardCount ? 'empty' : good ? 'good' :
        matching.length || result.cards.some(card => card.nearby) ? 'partial' : 'poor';
      totals[rating]++;
      grades[rating]++;
      if (rating !== 'good') console.log(JSON.stringify({group, rating, ...result}));
    }
  }
  console.log('Round 6 emergency top 3: ' + grades.good + ' good / ' + grades.partial + ' partial / ' +
    grades.poor + ' poor / ' + grades.empty + ' empty (floors 26 good, 0 empty)');
  console.log(JSON.stringify(groups));
  return grades;
}

function round7Url(url, group, sample) {
  return group === 'exact' || sample.single
    ? searchUrl(join(dirname(fileURLToPath(url)), 'single', sample.asset, 'START_HERE.html')) : url;
}

async function measureRound7(browser, url) {
  const files = {
    fao_good_dairy_practice: 'fao_good_dairy_practice_2011.pdf',
    fao_dairy_manual_vol1: 'fao_dairy_manual_vol1_1993.pdf',
    survival_shelter: 'Army_Survival_ATP_3_50_21_2018.pdf',
    navigation: 'USGS_Map_and_Compass.pdf',
  };
  const summary = {};
  for (const [group, samples] of Object.entries(round7)) {
    const totals = summary[group] = {good: 0, empty: 0};
    for (const sample of samples) {
      const result = await measure(browser, round7Url(url, group, sample), sample.query, {allowEmpty: true});
      const first = result.cards[0];
      const good = sample.topics
        ? sample.topics.includes(first?.topic) && grade(sample, result).good
        : !result.emergency && first?.indexed &&
          sample.pages.some(page => first.href.endsWith('/' + files[sample.asset] + '#page=' + page));
      totals.good += Number(Boolean(good));
      totals.empty += Number(!result.cardCount);
      console.log(JSON.stringify({group, good: Boolean(good), ...result}));
    }
  }
  console.log('Round 7 reader: ' + JSON.stringify(summary));
  return summary;
}

function searchUrl(startPage) {
  const url = pathToFileURL(resolve(startPage));
  url.hash = '/search';
  return url.href;
}

async function main() {
  const {values, positionals} = parseArgs({allowPositionals: true, options: {
    check: {type: 'boolean'},
    round5: {type: 'boolean'},
    round6: {type: 'boolean'},
    round7: {type: 'boolean'},
    query: {type: 'string', multiple: true},
  }});
  if (positionals.length !== 1) {
    throw Error('Usage: node scripts/search_timing.cjs START_HERE.html [--check] [--round5 | --round6 | --round7 | --query TEXT ...]');
  }
  const url = searchUrl(positionals[0]);
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE_PATH});
  try {
    console.log(JSON.stringify({chromium: browser.version(), cpu_throttle: 4, offline: true}));
    if (values.round6) {
      const grades = await measureRound6(browser, url);
      if (values.check && (grades.good < 26 || grades.empty)) process.exitCode = 1;
      return;
    }
    if (values.round7) {
      const summary = await measureRound7(browser, url);
      if (values.check) assert.ok(Object.values(summary).every(group => group.good === 5 && !group.empty));
      return;
    }
    if (values.round5) {
      const calibration = values.check && await calibrate(browser, url);
      const summary = await measureRound5(browser, url);
      if (values.check) {
        assert.ok(summary.good >= 34 && !summary.emergency_empty && !summary.negation_failures);
        checkTiming(summary.practical, calibration);
        checkTiming(summary.misspelled, calibration);
      }
      return;
    }
    const results = [];
    for (const query of values.query ?? emergencyQueries) {
      const result = await measure(browser, url, query);
      if (values.check && query === emergencyFallback && (!result.emergency ||
          !result.status.startsWith('No reviewed guide matched') || !result.chunk_reads || result.cards.some(card => card.topic))) {
        throw Error('Expected an emergency index fallback for: ' + query);
      }
      if (values.check && semanticChecks.has(query) &&
          (!result.emergency || result.cards[0]?.topic !== semanticChecks.get(query))) {
        throw Error('Expected a semantic emergency guide for: ' + query);
      }
      results.push(result);
      console.log(JSON.stringify(result));
    }
    const first = Math.max(...results.map(result => result.first_ms));
    const complete = Math.max(...results.map(result => result.complete_ms));
    const withinTarget = first <= 300 && complete <= 3000;
    console.log(JSON.stringify({queries: results.length, max_first_ms: first, max_complete_ms: complete,
      within_16_gb_target: withinTarget}));
    if (values.check && process.env.OWL_SEARCH_LOCAL_TIMING === '1' && !withinTarget) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

module.exports = {measure, searchUrl, emergencyFallback, semanticChecks, grade, measureRound5, measureRound6,
  measureRound7, calibrate, checkTiming, timingBounds};
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
