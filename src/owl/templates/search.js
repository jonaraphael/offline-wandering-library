/* Small offline metadata search. No source files, network, or model required. */
(function (root) {
  'use strict';
  const FORMAT = 'owl-discovery-v1';
  const normalize = value => String(value || '').normalize('NFKC').toLowerCase().replace(/\s+/gu, ' ').trim();
  const tokens = value => [...new Set(normalize(value).match(/[\p{L}\p{N}]+/gu) || [])];
  function prepare(records) {
    if (!Array.isArray(records)) throw new Error('Invalid discovery records');
    return records.map(record => {
      if (!record || typeof record.id !== 'string' || typeof record.title !== 'string' || !safeHref(record.href)) throw new Error('Invalid discovery destination');
      const titles = [record.title, ...(record.aliases || [])].map(normalize);
      const headline = new Set(tokens(titles.join(' ')));
      const text = new Set(tokens([record.description, record.source_title, record.category, record.publisher,
        ...(record.labels || []), ...(record.shelves || [])].join(' ')));
      return {record, titles, headline, text};
    });
  }
  function eligible(r, shelf) {
    if (shelf === 'legacy') return r.legacy === true;
    if (shelf !== 'all-with-legacy' && r.legacy) return false;
    return ['all', 'all-with-legacy'].includes(shelf) || (r.shelves || []).includes(shelf);
  }
  function search(prepared, query, shelf = 'all', limit = 50) {
    const phrase = normalize(query), words = tokens(query);
    if (words.length > 32) throw new Error('Use at most 32 different search words.');
    if (!words.length) return [];
    const found = [];
    for (const {record, titles, headline, text} of prepared) {
      if (!eligible(record, shelf)) continue;
      let hits = 0, titleHits = 0;
      for (const word of words) {
        if (headline.has(word)) { hits++; titleHits++; }
        else if (text.has(word)) hits++;
      }
      if (!hits) continue;
      const exact = titles.includes(phrase), all = hits === words.length;
      found.push({record, score: (exact ? 100000 : all ? 10000 : 0) + hits * 100 + titleHits * 10});
    }
    found.sort((a, b) => b.score - a.score || a.record.title.localeCompare(b.record.title) || a.record.id.localeCompare(b.record.id));
    const seen = new Set();
    return found.filter(({record}) => {
      const key = record.href + '\0' + record.location;
      if (seen.has(key)) return false;
      seen.add(key); return true;
    }).slice(0, limit);
  }
  function safeHref(href) {
    if (typeof href !== 'string' || !href || /^[\/\\]/.test(href)) return false;
    try {
      const path = decodeURIComponent(href.split('#')[0]);
      return !/[\x00-\x1f\\?:]/.test(path) && !path.split('/').some(p => !p || p === '.' || p === '..');
    } catch (_) { return false; }
  }
  const api = {normalize, tokens, prepare, search, safeHref};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.OWLDiscovery = api;
  if (typeof document === 'undefined') return;
  const form = document.getElementById('searchForm');
  if (!form) return;
  const byId = id => document.getElementById(id);
  const status = byId('status'), results = byId('results'), button = byId('searchButton');
  const retry = byId('retryButton'), query = byId('query'), shelf = byId('shelf');
  const prefix = form.dataset.libraryRoot || '';
  if (!['', 'LIBRARY/'].includes(prefix)) return;
  let prepared = [], timer, loading = false, epoch = 0;
  function script(path) {
    return new Promise((resolve, reject) => {
      const tag = document.createElement('script');
      const timeout = setTimeout(() => { tag.remove(); reject(new Error('Search loading timed out.')); }, 15000);
      tag.src = prefix + path;
      tag.onload = () => { clearTimeout(timeout); tag.remove(); resolve(); };
      tag.onerror = () => { clearTimeout(timeout); tag.remove(); reject(new Error('This viewer could not load the local search files.')); };
      document.head.appendChild(tag);
    });
  }
  async function load() {
    if (loading) return;
    loading = true; retry.hidden = true; button.disabled = shelf.disabled = true;
    status.textContent = 'Loading titles, chapters, and topics…';
    try {
      let manifest, payload;
      root.OWLDiscoveryManifest = value => { manifest = value; };
      await script('SEARCH/manifest.js');
      if (!manifest || manifest.format !== FORMAT || !/^SEARCH\/data\/[a-f0-9]{64}\.js$/.test(manifest.path)) throw new Error('Invalid discovery manifest.');
      root.OWLDiscoveryData = value => { payload = value; };
      await script(manifest.path);
      if (!payload || payload.format !== FORMAT || payload.generation !== manifest.generation || !Array.isArray(payload.records) || payload.records.length !== manifest.records) throw new Error('Discovery data does not match its manifest.');
      prepared = prepare(payload.records);
      form.hidden = false; byId('viewerHelp').hidden = true; button.disabled = shelf.disabled = false;
      status.textContent = `${prepared.length.toLocaleString()} titles, chapters, and topics ready. Document body text is not searched.`;
    } catch (error) { status.textContent = error.message + ' Use the static indexes below.'; retry.hidden = false; }
    finally { loading = false; delete root.OWLDiscoveryManifest; delete root.OWLDiscoveryData; }
  }
  function element(tag, text) { const e = document.createElement(tag); e.textContent = text; return e; }
  function link(href, text) { const e = element('a', text); e.href = prefix + href; return e; }
  async function run(event) {
    if (event) event.preventDefault();
    clearTimeout(timer);
    const mine = ++epoch;
    results.replaceChildren(); status.textContent = 'Searching titles, chapters, and topics…';
    await new Promise(resolve => setTimeout(resolve, 0));
    if (mine !== epoch) return;
    try {
      const matches = search(prepared, query.value, shelf.value);
      for (const {record: r} of matches) {
        const li = document.createElement('li');
        li.append(link(r.href, r.title));
        li.append(element('p', `${r.source_title} · ${r.location}${r.reader_required ? ' · Compatible reader required' : ''}`));
        if (r.description) li.append(element('p', r.description));
        if (r.kind === 'section') li.append(link(r.destination.split('/').map(encodeURIComponent).join('/'), 'Open complete document'));
        if (r.license || r.attribution) li.append(element('small', [r.license, r.attribution].filter(Boolean).join(' · ')));
        results.append(li);
      }
      status.textContent = matches.length ? `${matches.length} result${matches.length === 1 ? '' : 's'} shown.` :
        'No matching title, chapter, or topic. Browse the atlas or search inside a relevant book/archive; body text is not searched here.';
    } catch (error) { status.textContent = error.message; }
  }
  form.addEventListener('submit', run);
  query.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 180); });
  shelf.addEventListener('change', run);
  retry.addEventListener('click', load);
  load();
})(globalThis);
