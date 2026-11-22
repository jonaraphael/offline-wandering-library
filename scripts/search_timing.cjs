#!/usr/bin/env node
/* Time the shipped reader from a local file in offline, CPU-throttled Chromium. */
'use strict';
const {parseArgs} = require('node:util');
const {statSync} = require('node:fs');
const {resolve} = require('node:path');
const {fileURLToPath, pathToFileURL} = require('node:url');
const {chromium} = require('playwright-core');

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

async function measure(browser, url, query, {allowEmpty = false} = {}) {
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
    const {cards, cardCount} = await page.locator('#search-results article.result:visible').evaluateAll(elements => ({
      cardCount: elements.length,
      cards: elements.slice(0, 3).map(card => ({
        title: card.querySelector('h3').textContent,
        topic: card.dataset.reviewed,
        nearby: card.dataset.nearby,
        indexed: card.dataset.indexed === 'true',
        href: card.querySelector('a.button').getAttribute('href'),
        locator: card.querySelector('small')?.textContent,
      })),
    }));
    const browse = await page.locator('#search-results > a.button:visible').evaluateAll(elements =>
      elements.map(link => [link.textContent, link.getAttribute('href')]));
    const paths = reads.filter(url => url.protocol === 'file:').map(url => fileURLToPath(url));
    return {query, first_ms: first === undefined ? null : Math.round(first * 10) / 10,
      complete_ms: Math.round(complete * 10) / 10,
      bytes: paths.reduce((sum, path) => sum + statSync(path).size, 0), reads: paths.length,
      chunk_reads: paths.filter(path => /[\\/]SEARCH[\\/](?:chunks|sources)[\\/]/.test(path)).length,
      emergency, status, cards, cardCount, browse};
  } finally {
    await context.close();
  }
}

function searchUrl(startPage) {
  const url = pathToFileURL(resolve(startPage));
  url.hash = '/search';
  return url.href;
}

async function main() {
  const {values, positionals} = parseArgs({allowPositionals: true, options: {
    check: {type: 'boolean'},
    query: {type: 'string', multiple: true},
  }});
  if (positionals.length !== 1) throw Error('Usage: node scripts/search_timing.cjs START_HERE.html [--check] [--query TEXT]');
  const url = searchUrl(positionals[0]);
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE_PATH});
  try {
    console.log(JSON.stringify({chromium: browser.version(), cpu_throttle: 4, offline: true}));
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
    if (values.check && !withinTarget) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

module.exports = {measure, searchUrl, emergencyFallback, semanticChecks};
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
