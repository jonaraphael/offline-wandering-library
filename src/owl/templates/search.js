/* Small offline metadata search. No source files, network, or model required. */
(function (root) {
  'use strict';
  const FORMAT = 'owl-discovery-v1';
  const generation = typeof document === 'undefined' ? '' :
    document.currentScript?.getAttribute('src')?.match(/^LIBRARY\/(INDEX\/[0-9a-f]{12})\/search\.js$/)?.[1] || '';
  const local = path => (generation || 'SEARCH') + '/' + path;
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
  function findUrgent(tasks, text) {
    const phrase = ' ' + (normalize(text).match(/[\p{L}\p{N}]+/gu) || []).join(' ') + ' ';
    return tasks.filter(task => task.href).map(task => {
      const score = Math.max(0, ...[task.task, ...task.keywords].map(value => {
        const words = tokens(value).join(' ');
        return phrase.includes(' ' + words + ' ') ? words.length : 0;
      }));
      return {task, score};
    }).filter(row => row.score).sort((a, b) => b.score - a.score)[0]?.task;
  }
  function heading(record) {
    const source = record.source_title || '';
    let title = record.title;
    if (record.location && title.endsWith(' · ' + record.location)) {
      title = title.slice(0, -record.location.length - 3);
    }
    if (source && title.startsWith(source + ' · ')) title = title.slice(source.length + 3);
    return !title || title === 'Section' ? source : title;
  }
  function orderedMatches(indexed, metadata, priority, words, terms, urgent, pediatricHealth) {
    const seen = new Set(), indexedFiles = new Set(indexed.map(({record}) => record.asset_id));
    const matches = [...indexed, ...metadata.filter(({record}) =>
      record.kind !== 'document' || !indexedFiles.has(record.asset_id))].filter(({record}) => {
      const key = record.href + '\0' + record.location;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    const score = hit => {
      const {record} = hit;
      const boost = isArchive(record) ? 0 : (Object.hasOwn(priority, record.asset_id) ? priority[record.asset_id] * 8 : 0);
      const title = heading(record) + ' ' + (record.source_title || '');
      const titleTerms = new Set(terms(title));
      const titleMatches = words.filter(word => titleTerms.has(word)).length;
      const titleScore = titleMatches && titleMatches === words.length ? 32 : 0;
      if (hit.indexed) {
        const guide = record.asset_id === urgent?.id ? 28 : 0;
        const childIllness = pediatricHealth && /\b(?:health and sicknesses of children|fever|childhood illnesses)\b/i.test(title) ? 18 : 0;
        return hit.score + boost + titleScore + guide + childIllness;
      }
      const lexical = hit.score % 10000 / 110;
      const exact = hit.score >= 100000;
      return (exact ? 150 : 20 + lexical * 12) + boost + titleScore;
    };
    return matches.map(hit => ({...hit, displayScore: score(hit)}))
      .sort((a, b) => b.displayScore - a.displayScore);
  }

  function closeMatch(matches, words, terms) {
    if (!words.length) return false;
    const documents = matches.filter(({record}) => record.kind !== 'topic');
    const direct = documents.filter(({record}) => !isArchive(record));
    return (direct.length ? direct : documents).some(hit => {
      if (hit.focused || hit.score >= 100000 && !hit.indexed) return true;
      const {record} = hit;
      const evidence = new Set(terms([heading(record), record.source_title, record.description].join(' ')));
      const covered = words.filter(word => evidence.has(word)).length;
      return covered >= Math.max(1, Math.ceil(words.length * 0.75)) &&
        (hit.indexed ? hit.score >= 65 : hit.displayScore >= 48);
    });
  }

  function suggestions(matches, words, terms) {
    const relevant = matches.filter(({record}) => {
      if (record.kind === 'topic') return false;
      const evidence = new Set(terms([heading(record), record.source_title, record.description].join(' ')));
      return words.filter(word => evidence.has(word)).length >= Math.min(2, words.length);
    });
    return (relevant.length ? relevant : matches).slice(0, 10);
  }

  async function loadRank(categoryIds) {
    let selection, table, paths = {};
    root.OWLShardSelection = value => { selection = value; };
    root.OWLShardModel = value => { table = value; };
    root.OWLSearchPaths = value => { paths = value; };
    try {
      if (generation) await script(local('search-paths.js'));
      const sharedScript = path => {
        if (!generation) return script(path);
        if (/^SEARCH\/(?:chunks|sources)\/[a-f0-9]{64}(?:\/\d{5})?\.js$/.test(path)) return script(path);
        const pinned = paths[path];
        if (!/^SEARCH\/shared\/[a-f0-9]{64}\.js$/.test(pinned)) return Promise.reject(Error('Missing pinned search file.'));
        return script(pinned);
      };
      await Promise.all([script(local('rank.js')), script(local('shards.js')), sharedScript('SEARCH/model.js')]);
      const ranker = root.OWLShardRank;
      const indexed = ranker.classic(sharedScript, selection, table, async (index, encode, read, query, category, ...options) => {
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
          reranker ??= script(local('rerank.js')).then(() => root.OWLReranker.create(sharedScript));
          const rerank = await reranker;
          const head = all.slice(0, 3);
          const shortlist = all.slice(3, 53);
          const rescored = await rerank(text, shortlist, cancelled);
          const remaining = [...rescored, ...all.slice(head.length + shortlist.length)];
          return cancelled() ? [] : [...head, ...ranker.topResults(remaining, limit - head.length)];
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
      delete root.OWLSearchPaths;
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

  function mount(view, {open, openUrgent, tasks = [], priority = {}, categoryIds}) {
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
        await script(local('manifest.js'));
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
    function render(matches, scope, words = [], urgent) {
      const groups = [new Map(), new Map()], subjects = [];
      for (const match of matches) {
        if (match.record.kind === 'topic') {
          subjects.push(match.record);
          continue;
        }
        const bucket = groups[Number(isArchive(match.record))];
        const key = match.record.destination || match.record.href.split('#')[0];
        if (!bucket.has(key)) bucket.set(key, []);
        bucket.get(key).push(match);
      }
      const items = document.createDocumentFragment();
      if (urgent) {
        const card = element('article', '', 'result urgent-result');
        card.append(element('span', 'Urgent', 'label urgent'), element('h3', urgent.task));
        const archive = urgent.format === 'zim';
        const link = element('a', archive ? 'How to open' : 'Open', 'button');
        link.href = archive ? '#open-encyclopedia' : urgent.href;
        if (archive) link.setAttribute('aria-haspopup', 'dialog');
        link.addEventListener('click', event => {
          if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
            openUrgent(urgent, event);
          }
        });
        card.append(link);
        items.append(card);
      }
      function resultCard([{record, indexed = false}, ...others]) {
        const card = element('article', '', 'result');
        card.dataset.indexed = String(indexed);
        const archive = isArchive(record), name = heading(record);
        const source = record.source_title !== name ? record.source_title : '';
        const where = archive ? 'opens in Kiwix' : record.location;
        const byline = [source, where].filter(Boolean).join(' · ');
        if (byline) card.append(element('small', byline));
        card.append(element('h3', name));
        if (record.description) card.append(passage(/[.!?…:]$/.test(record.description)
          ? record.description : record.description + '…', words));
        const locations = new Set([record.href + '\0' + record.location]);
        const places = others.filter(({record: other}) => {
          if (other.kind !== 'section' && other.kind !== 'article' && !other.href.includes('#')) return false;
          const key = other.href + '\0' + other.location;
          if (locations.has(key)) return false;
          locations.add(key);
          return true;
        }).slice(0, 3);
        if (places.length) {
          card.append(element('p', 'Also in this document', 'also-label'));
          const more = element('ul', '', 'also');
          more.setAttribute('aria-label', 'Also in this document');
          for (const {record: other} of places) {
            const item = element('li', '');
            const title = heading(other);
            item.append(resultLink(other, title, title === name && other.location ? other.location : title));
            more.append(item);
          }
          card.append(more);
        }
        if (archive && record.kind !== 'document') {
          card.append(element('p', 'In Kiwix, look up “' + name + '”.', 'note'));
        }
        card.append(resultLink(record, name, archive ? 'How to open' : 'Open', 'button'));
        return card;
      }
      for (const group of groups) {
        if (!group.size) continue;
        const section = element('section', '', 'result-group');
        if (group === groups[1]) {
          section.append(element('h2', 'In encyclopedias (open in Kiwix)', 'label encyclopedia-results'));
        }
        for (const hits of group.values()) section.append(resultCard(hits));
        items.append(section);
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
      return groups[0].size + groups[1].size + subjects.length + Number(Boolean(urgent));
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
        const words = tokens(text);
        let terms = tokens, queryTerms = words, intent;
        const catalog = search(scope, text, 'all', 90);
        const urgent = findUrgent(tasks, text);
        let matches, count, warning = '';
        const showHits = (hits, phase) => {
          matches = orderedMatches(hits, catalog, priority, queryTerms, terms, urgent, intent?.pediatricHealth);
          count = render(matches.slice(0, 70), phase, words, urgent);
        };
        showHits([], 'catalog');
        if (rankReady) {
          message('Searching…');
          try {
            const engine = await rankReady;
            if (cancelled()) return;
            warning = engine.warning || '';
            if (engine.rank) {
              const ranker = root.OWLShardRank;
              terms = ranker.terms;
              intent = ranker.prepareQuery(text, () => null);
              queryTerms = intent.query;
              let rankedText = text;
              if (!intent.emergency && urgent?.keywords.includes('wound')) rankedText += ' wound care';
              if (!intent.emergency && urgent?.keywords.includes('scald')) rankedText += ' burn treatment';
              if (!intent.deliveryQuery && !intent.postpartum && urgent?.keywords.includes('childbirth')) rankedText += ' childbirth';
              const hits = await engine.rank(rankedText, selected, 85, cancelled, (hits, phase) => {
                if (cancelled()) return;
                showHits(hits, 'indexed');
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
        const close = urgent || closeMatch(matches, queryTerms, terms);
        if (count && !close) count = render(suggestions(matches, queryTerms, terms), list.dataset.searchScope, words);
        message([warning, count ? close
          ? count + ' result' + (count === 1 ? '' : 's') + ', best first.'
          : 'No close match. These may help:'
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

  const api = {normalize, tokens, prepare, search, mergeRanked, safeHref, script, local, isArchive, mount};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.OWLDiscovery = api;
  if (typeof document !== 'undefined' && document.querySelector('#reader-view')) {
    script(generation ? local('reader.js') : 'INDEX/reader.js').catch(() => {});
  }
})(globalThis);
