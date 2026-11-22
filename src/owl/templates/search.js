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
  function script(path) {
    return new Promise((resolve, reject) => {
      const tag = document.createElement('script');
      const finish = error => {
        clearTimeout(timeout);
        tag.remove();
        if (error) reject(Error(error));
        else resolve();
      };
      const timeout = setTimeout(() => finish('Loading local files timed out.'), 15000);
      tag.src = 'LIBRARY/' + path;
      tag.onload = () => finish();
      tag.onerror = () => finish('This viewer could not load the local files.');
      document.head.appendChild(tag);
    });
  }
  function isArchive(record) {
    return record.kind === 'article' || /\.zim(?:[a-z]{2})?$/i.test((record.destination || record.href).split('#')[0]);
  }
  async function loadRank(categoryIds) {
    let selection, table;
    root.OWLShardSelection = value => { selection = value; };
    root.OWLShardModel = value => { table = value; };
    try {
      await Promise.all([script('SEARCH/rank.js'), script('SEARCH/shards.js'), script('SEARCH/model.js')]);
      const ranker = root.OWLShardRank;
      const indexed = ranker.classic(script, selection, table, async (index, encode, read, query, category, ...options) => {
        const ids = category && await categoryIds(category);
        const scoped = ids ? {...index, sources: index.sources.filter(source => ids.has(source.id))} : index;
        return ranker.search(scoped, encode, read, query, 'all', ...options);
      });
      const mobile = navigator.userAgentData?.mobile ?? /Android|iPhone|iPad/i.test(navigator.userAgent);
      if (!selection.reranker || mobile) return {rank: indexed};
      let reranker;
      async function rank(text, category, limit, cancelled, onProgress) {
        const all = await indexed(text, category, Math.max(limit, 50), cancelled,
          (hits, scope) => onProgress(hits.slice(0, limit), scope));
        const initial = all.slice(0, limit);
        if (cancelled() || initial.length < 2) return initial;
        onProgress(initial, 'ranked');
        try {
          reranker ??= script('SEARCH/rerank.js').then(() => root.OWLReranker.create(script));
          const rerank = await reranker;
          const head = all.slice(0, 3);
          const rescored = await rerank(text, all.slice(3), cancelled);
          return cancelled() ? [] : [...head, ...ranker.topResults(rescored, limit - head.length)];
        } catch (_) {
          reranker = undefined;
          return initial;
        }
      }
      return {rank};
    } catch (_) {
      return {warning: 'Full-text search is unavailable. Search still covers titles and topics.'};
    } finally {
      delete root.OWLShardSelection;
      delete root.OWLShardModel;
    }
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function passage(text, words) {
    const node = element('p', '', 'text');
    const pattern = words.length ? new RegExp('(' + words.map(word =>
      word.replace(/[.*+?^$${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'giu') : null;
    for (const [index, part] of (pattern ? text.split(pattern) : [text]).entries()) {
      node.append(index % 2 ? element('mark', part) : document.createTextNode(part));
    }
    return node;
  }

  function mount(view, {open, categoryIds}) {
    const form = view.querySelector('form'), status = view.querySelector('#search-status');
    const list = view.querySelector('#search-results'), query = form.querySelector('#query');
    const category = form.querySelector('#search-category'), examples = form.querySelector('#search-examples');
    let timer, epoch = 0, prepared, rankReady;
    function message(text) {
      status.textContent = text;
      status.hidden = !text;
    }
    async function load() {
      message('Getting search ready…');
      let manifest, payload;
      root.OWLDiscoveryManifest = value => { manifest = value; };
      try {
        await script('SEARCH/manifest.js');
        if (manifest?.format !== FORMAT || !/^SEARCH\/data\/[a-f0-9]{64}\.js$/.test(manifest.path)) {
          throw Error('The search information could not be read.');
        }
        root.OWLDiscoveryData = value => { payload = value; };
        await script(manifest.path);
        if (payload?.format !== FORMAT || payload.generation !== manifest.generation ||
            !Array.isArray(payload.records) || payload.records.length !== manifest.records) {
          throw Error('The search information does not match this drive.');
        }
        prepared = prepare(payload.records);
        if (manifest.shards) rankReady = loadRank(categoryIds);
        message('');
      } catch (error) {
        message(error.message + ' Browse the books and guides from Home.');
      } finally {
        delete root.OWLDiscoveryManifest;
        delete root.OWLDiscoveryData;
      }
    }
    const ready = load();

    function resultLink(record, name, text, className) {
      const anchor = element('a', text, className);
      const topic = record.kind === 'topic';
      const archive = isArchive(record);
      anchor.href = topic ? '#/topic/' + encodeURIComponent(record.id.slice('topic:'.length))
        : archive ? '#open-encyclopedia' : 'LIBRARY/' + record.href;
      if (archive) anchor.setAttribute('aria-haspopup', 'dialog');
      anchor.addEventListener('click', event => {
        if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
          open(record, name, event);
        }
      });
      return anchor;
    }
    // One card per document, with its best match and a few distinct locations.
    function render(matches, scope, words = []) {
      const groups = new Map(), subjects = [];
      for (const match of matches) {
        if (match.record.kind === 'topic') {
          subjects.push(match.record);
          continue;
        }
        const key = match.record.destination || match.record.href.split('#')[0];
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(match);
      }
      const items = document.createDocumentFragment();
      const title = row => row.location && row.title.endsWith(' · ' + row.location)
        ? row.title.slice(0, -row.location.length - 3) : row.title;
      for (const [{record: record, indexed = false}, ...others] of groups.values()) {
        const card = element('article', '', 'result');
        card.dataset.indexed = String(indexed);
        const archive = isArchive(record), name = title(record);
        const source = record.source_title !== name ? record.source_title : '';
        const where = archive ? 'opens in Kiwix' : record.location;
        const byline = [source, where].filter(Boolean).join(' · ');
        if (byline) card.append(element('small', byline));
        card.append(element('h3', name));
        if (record.description) card.append(passage(/[.!?…:]$/.test(record.description)
          ? record.description : record.description + '…', words));
        const places = others.filter(({record: other}) => other.kind === 'section' || other.kind === 'article' ||
          other.href.includes('#')).slice(0, 4);
        if (places.length) {
          const more = element('ul', '', 'also');
          more.setAttribute('aria-label', 'Other matches in this document');
          for (const {record: other} of places) {
            const item = element('li', '');
            item.append(resultLink(other, title(other), title(other)));
            more.append(item);
          }
          card.append(more);
        }
        if (archive && record.kind !== 'document') {
          card.append(element('p', 'In Kiwix, look up “' + name + '”.', 'note'));
        }
        card.append(resultLink(record, name, archive ? 'How to open' : 'Open', 'button'));
        items.append(card);
      }
      if (subjects.length) {
        const panel = element('section', '', 'panel');
        panel.append(element('h3', 'Subjects'));
        const links = element('div', '', 'chips plain');
        for (const subject of subjects) links.append(resultLink(subject, subject.title, subject.title));
        panel.append(links);
        items.append(panel);
      }
      list.replaceChildren(items);
      list.dataset.searchScope = scope;
      return groups.size + subjects.length;
    }
    async function run(event) {
      event?.preventDefault();
      clearTimeout(timer);
      const mine = ++epoch;
      const cancelled = () => mine !== epoch;
      const text = query.value.trim(), selected = category.value;
      examples.hidden = Boolean(text);
      if (!text) {
        render([], 'catalog');
        if (prepared) message('');
        return;
      }
      await ready;
      if (cancelled() || !prepared) return;
      try {
        const ids = selected && await categoryIds(selected);
        if (cancelled()) return;
        const scope = ids ? prepared.filter(({record}) => ids.has(record.asset_id) ||
          record.kind === 'topic' && record.source_ids.some(id => ids.has(id))) : prepared;
        const catalog = search(scope, text), words = tokens(text);
        let count = render(catalog.slice(0, 40), 'catalog', words), warning = '';
        if (rankReady) {
          message('Searching…');
          const showHits = (hits, phase) => {
            count = render(mergeRanked(hits, catalog), phase, words);
          };
          try {
            const engine = await rankReady;
            if (cancelled()) return;
            warning = engine.warning || '';
            if (engine.rank) {
              const hits = await engine.rank(text, selected, 30, cancelled, (hits, phase) => {
                if (cancelled()) return;
                showHits(hits, phase === 'ranked' ? 'complete' : 'indexed');
                if (phase === 'refining' || phase === 'ranked') message('Still looking for better matches…');
              });
              if (cancelled()) return;
              showHits(hits, 'complete');
            }
          } catch (error) {
            if (cancelled()) return;
            warning = error.message + ' Showing what was found.';
          }
        }
        message([warning, count ? count + ' result' + (count === 1 ? '' : 's') + ', best first.'
          : 'Nothing found. Try fewer or different words.'].filter(Boolean).join(' '));
      } catch (error) {
        render([], 'catalog');
        message(error.message);
      }
    }
    form.addEventListener('submit', run);
    query.addEventListener('input', () => {
      clearTimeout(timer);
      ++epoch;
      examples.hidden = Boolean(query.value.trim());
      if (!query.value.trim()) run();
      else timer = setTimeout(run, 350);
    });
    for (const example of form.querySelectorAll('[data-query]')) {
      example.addEventListener('click', () => { query.value = example.dataset.query; query.focus(); run(); });
    }
    category.addEventListener('change', run);
  }

  const api = {normalize, tokens, prepare, search, mergeRanked, safeHref, script, isArchive, mount};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.OWLDiscovery = api;
  if (typeof document !== 'undefined' && document.querySelector('#reader-view')) {
    script('INDEX/reader.js').catch(() => {});
  }
})(globalThis);
