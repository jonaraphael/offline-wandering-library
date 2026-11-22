#!/usr/bin/env node
/* Time the shipped reader from a local file in offline, CPU-throttled Chromium. */
'use strict';
const {parseArgs} = require('node:util');
const {statSync} = require('node:fs');
const {resolve} = require('node:path');
const {fileURLToPath, pathToFileURL} = require('node:url');
const {chromium} = require('playwright-core');

const emergencyQueries = [
  'signs of dehydration',
  'chest compressions',
  'snake bite',
  'make water safe to drink',
  'we are stuck outside overnight in heavy rain without a tent',
];

async function measure(browser, url, query) {
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
        if (sample.first === undefined && results.querySelector('[data-indexed="true"]')) {
          sample.first = performance.now() - started;
        }
        if (results.dataset.searchScope === 'complete' && !status.hidden) {
          sample.complete = performance.now() - started;
          sample.status = status.textContent;
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
    const {first, complete, status, error} = await page.evaluate(() => window.searchTiming);
    const remote = reads.filter(url => !['file:', 'blob:'].includes(url.protocol));
    if (error || first === undefined || failures.length || remote.length) {
      throw Error(error || 'Search did not return indexed results using only local files: ' +
        [...failures, ...remote].join(', '));
    }
    const paths = reads.filter(url => url.protocol === 'file:').map(url => fileURLToPath(url));
    return {query, first_ms: Math.round(first * 10) / 10, complete_ms: Math.round(complete * 10) / 10,
      bytes: paths.reduce((sum, path) => sum + statSync(path).size, 0), reads: paths.length, status};
  } finally {
    await context.close();
  }
}

async function main() {
  const {values, positionals} = parseArgs({allowPositionals: true, options: {
    check: {type: 'boolean'},
    query: {type: 'string', multiple: true},
  }});
  if (positionals.length !== 1) throw Error('Usage: node scripts/search_timing.cjs START_HERE.html [--check] [--query TEXT]');
  const url = pathToFileURL(resolve(positionals[0]));
  url.hash = '/search';
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE_PATH});
  try {
    console.log(JSON.stringify({chromium: browser.version(), cpu_throttle: 4, offline: true}));
    const results = [];
    for (const query of values.query ?? emergencyQueries) {
      const result = await measure(browser, url.href, query);
      results.push(result);
      console.log(JSON.stringify(result));
    }
    const first = Math.max(...results.map(result => result.first_ms));
    const complete = Math.max(...results.map(result => result.complete_ms));
    const withinTarget = first < 300 && complete <= 3000;
    console.log(JSON.stringify({queries: results.length, max_first_ms: first, max_complete_ms: complete,
      within_16_gb_target: withinTarget}));
    if (values.check && !withinTarget) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
