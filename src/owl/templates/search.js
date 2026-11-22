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
  function mergeRanked(indexed, metadata, limit = 40) {
    const exact = metadata.filter(hit => hit.score >= 100000).slice(0, 2);
    const full = metadata.filter(hit => hit.score >= 10000 && hit.score < 100000).slice(0, 2);
    const seen = new Set();
    const first = indexed.slice(0, 3);
    const head = first[0]?.focused ? [...first, ...exact] : [...exact, ...first];
    return [...head, ...full, ...indexed.slice(3), ...metadata].filter(({record}) => {
      const key = record.href + '\0' + record.location;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, limit);
  }
  function safeHref(href) {
    if (typeof href !== 'string' || !href || /^[\/\\]/.test(href)) return false;
    try {
      const path = decodeURIComponent(href.split('#')[0]);
      return !/[\x00-\x1f\\?:]/.test(path) && !path.split('/').some(p => !p || p === '.' || p === '..');
    } catch (_) { return false; }
  }
  const api = {normalize, tokens, prepare, search, mergeRanked, safeHref};
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
  // This script loaded from the drive, so this viewer follows local links:
  // pages can hide the printed folder paths kept for viewers that do not.
  document.documentElement.classList.add('live');
  for (const fold of document.querySelectorAll('details[open]')) fold.open = false;
  let prepared = [], rankReady, timer, loading = false, epoch = 0;
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
    status.textContent = 'Getting search ready…';
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
      status.textContent = '';
      rankReady = manifest.shards ? loadRank() : null;
      rankReady?.then(({rank, warning}) => {
        if (!epoch && !rank) status.textContent = warning + ' Titles and topics can still be searched.';
      });
    } catch (error) { status.textContent = error.message + ' Use the lists on this page instead.'; retry.hidden = false; }
    finally { loading = false; delete root.OWLDiscoveryManifest; delete root.OWLDiscoveryData; }
  }
  async function loadRank() {
    let selection, table;
    root.OWLShardSelection = value => { selection = value; };
    root.OWLShardModel = value => { table = value; };
    try {
      await Promise.all([script('SEARCH/rank.js'), script('SEARCH/shards.js'), script('SEARCH/model.js')]);
      const indexed = root.OWLShardRank.classic(script, selection, table);
      const mobile = navigator.userAgentData?.mobile ?? /Android|iPhone|iPad/i.test(navigator.userAgent);
      if (!selection.reranker || mobile) return {rank: indexed};
      let reranker;
      async function rank(text, shelf, limit, cancelled, onProgress) {
        const all = await indexed(text, shelf, Math.max(limit, 50), cancelled,
          (hits, scope) => onProgress(hits.slice(0, limit), scope));
        const initial = all.slice(0, limit);
        if (cancelled() || initial.length < 2) return initial;
        onProgress(initial, 'ranked');
        try {
          reranker ??= script('SEARCH/rerank.js').then(() => root.OWLReranker.create(script));
          const rerank = await reranker;
          const head = all.slice(0, 3);
          const rescored = await rerank(text, all.slice(3), cancelled);
          return cancelled() ? [] : [...head, ...root.OWLShardRank.topResults(rescored, limit - head.length)];
        } catch (_) {
          reranker = undefined;
          return initial;
        }
      }
      return {rank};
    } catch (_) {
      return {warning: 'The full-text index could not load.'};
    } finally {
      delete root.OWLShardSelection;
      delete root.OWLShardModel;
    }
  }
  function element(tag, text, className) {
    const e = document.createElement(tag);
    e.textContent = text;
    if (className) e.className = className;
    return e;
  }
  function link(href, text, className) { const e = element('a', text, className); e.href = prefix + href; return e; }
  // Mark the searched words in a passage.
  function passage(text, words) {
    const node = element('p', '', 'text');
    const pattern = words.length ? new RegExp('(' + words.map(word => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'giu') : null;
    for (const [index, part] of (pattern ? text.split(pattern) : [text]).entries()) {
      node.append(index % 2 ? element('mark', part) : document.createTextNode(part));
    }
    return node;
  }
  // One card per document: its best match first, then other matching places in it.
  function render(matches, scope, words = []) {
    const groups = new Map();
    for (const match of matches) {
      const key = match.record.destination || match.record.href.split('#')[0];
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(match);
    }
    const items = document.createDocumentFragment();
    for (const [{record: r, indexed = false}, ...others] of groups.values()) {
      const li = document.createElement('li');
      li.dataset.indexed = String(indexed);
      const archive = Boolean(r.reader_required);
      // A passage title repeats its page; the page is shown once, on the line below.
      const name = r.location && r.title.endsWith(' · ' + r.location) ? r.title.slice(0, -r.location.length - 3) : r.title;
      li.append(link(r.href, name, 'hit'));
      const source = r.source_title && r.source_title !== name ? r.source_title : '';
      const where = archive ? 'Open it in the Kiwix app, then search there for “' + name + '”' : r.location;
      li.append(element('p', [source, where].filter(Boolean).join(' · '), 'from'));
      if (r.description) li.append(passage(/[.!?…:]$/.test(r.description) ? r.description : r.description + '…', words));
      const more = element('p', '', 'more');
      // The whole-document entry is offered once, by the link below.
      const places = others.filter(({record}) => record.kind === 'section' || record.href.includes('#'));
      for (const {record: other} of places.slice(0, 4)) more.append(link(other.href, other.location || other.title));
      if (r.kind === 'section') more.append(link(r.destination.split('/').map(encodeURIComponent).join('/'), 'Open the whole document'));
      if (more.childNodes.length) { more.prepend(places.length ? 'Also in this document: ' : ''); li.append(more); }
      if (r.license || r.attribution) li.append(element('small', [r.license, r.attribution].filter(Boolean).join(' · ')));
      items.append(li);
    }
    results.replaceChildren(items);
    results.dataset.searchScope = scope;
  }
  async function run(event) {
    if (event) event.preventDefault();
    clearTimeout(timer);
    const mine = ++epoch;
    const cancelled = () => mine !== epoch;
    const text = query.value, selectedShelf = shelf.value;
    try {
      const catalog = search(prepared, text, selectedShelf), words = tokens(text);
      render(catalog.slice(0, 40), 'catalog', words);
      let matches = catalog.slice(0, 40);
      let warning = '';
      if (rankReady && text.trim()) {
        status.textContent = 'Searching…';
        const showHits = (hits, scope) => {
          matches = mergeRanked(hits, catalog);
          render(matches, scope, words);
        };
        try {
          const engine = await rankReady;
          if (cancelled()) return;
          warning = engine.warning || '';
          if (engine.rank) {
            const hits = await engine.rank(text, selectedShelf, 30, cancelled, (hits, phase) => {
              if (cancelled()) return;
              showHits(hits, phase === 'ranked' ? 'complete' : 'indexed');
              if (phase === 'refining' || phase === 'ranked') status.textContent = 'Still looking for better matches…';
            });
            if (cancelled()) return;
            showHits(hits, 'complete');
          }
        } catch (error) {
          if (cancelled()) return;
          warning = error.message + ' Showing what was found.';
        }
      }
      status.textContent = [warning, !text.trim() ? '' : matches.length
        ? `${matches.length} result${matches.length === 1 ? '' : 's'}, best first.`
        : 'Nothing found. Try fewer or different words.'].filter(Boolean).join(' ');
    } catch (error) {
      render([], 'catalog');
      status.textContent = error.message;
    }
  }
  form.addEventListener('submit', run);
  query.addEventListener('input', () => {
    clearTimeout(timer);
    if (!query.value.trim()) run();
    else if (rankReady) ++epoch;
    else timer = setTimeout(run, 180);
  });
  for (const example of form.querySelectorAll('[data-query]')) {
    example.addEventListener('click', () => { query.value = example.dataset.query; run(); });
  }
  shelf.addEventListener('change', run);
  retry.addEventListener('click', load);
  load();
})(globalThis);
