/* Offline ranking over independently packed, selected source shards. */
(function (root) {
  'use strict';
  const stop = new Set('a an and are as at be by do does for from how i in is it of on or the to use what when where with you your'.split(' '));
  const words = text => text.toLowerCase().normalize('NFKD').replace(/\p{M}/gu, '').match(/[\p{L}\p{N}]+/gu) || [];
  const normalize = text => words(text).join(' ');

  function stem(word) {
    if (word.length > 4 && word.endsWith('ies')) return word.slice(0, -3) + 'y';
    if (word.length > 5 && word.endsWith('oes')) return word.slice(0, -2);
    for (const suffix of ['ing', 'ed', 'es', 's']) {
      if (word.length > suffix.length + 3 && word.endsWith(suffix) && !/(ss|us)$/.test(word)) {
        word = word.slice(0, -suffix.length);
        if ((suffix === 'ing' || suffix === 'ed') && /(bb|dd|gg|mm|nn|pp|rr|tt)$/.test(word)) word = word.slice(0, -1);
        break;
      }
    }
    return word.length > 4 && word.endsWith('e') ? word.slice(0, -1) : word;
  }

  function terms(text) {
    return [...new Set(words(text).filter(word => word.length > 1 && word.length <= 50 && !stop.has(word)).map(stem))];
  }

  function hashTerm(word) {
    let value = 2166136261;
    for (let index = 0; index < word.length; index++) value = Math.imul(value ^ word.charCodeAt(index), 16777619);
    return value >>> 0;
  }

  function mightMatch(bits, query) {
    return query.some(word => {
      const key = hashTerm(word);
      return [key & 65535, key >>> 16].every(bit => bits.charCodeAt(bit >>> 3) & (1 << (bit & 7)));
    });
  }

  function bytes(encoded) {
    return Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
  }

  function model(table) {
    const vocab = new Map(table.vocab.map((word, index) => [word, index]));
    const weights = bytes(table.weights), dim = table.scales.length;
    if (table.version !== 1 || dim !== 32 || weights.length !== vocab.size * dim) throw Error('Invalid search model');
    const signed = new Int8Array(weights.buffer);
    return text => {
      const normalized = text.slice(0, 4096).toLowerCase().normalize('NFD').replace(/\p{Mn}/gu, '');
      const vector = new Float64Array(dim);
      for (const word of normalized.match(/[\p{L}\p{N}]+/gu) || []) {
        if (word.length > 100) continue;
        const ids = [];
        for (let start = 0; start < word.length;) {
          let end = word.length, id;
          while (end > start) {
            id = vocab.get((start ? '##' : '') + word.slice(start, end));
            if (id !== undefined) break;
            end--;
          }
          if (end === start) { ids.length = 0; break; }
          ids.push(id);
          start = end;
        }
        for (const id of ids) {
          for (let col = 0; col < dim; col++) vector[col] += signed[id * dim + col];
        }
      }
      for (let col = 0; col < dim; col++) vector[col] *= table.scales[col];
      const norm = Math.hypot(...vector);
      return norm ? Float64Array.from(vector, value => value / norm / 127) : null;
    };
  }

  async function unpack(encoded) {
    const stream = new Blob([bytes(encoded)]).stream().pipeThrough(new DecompressionStream('gzip'));
    const chunk = await new Response(stream).json();
    chunk.vectors = chunk.records.flatMap((row, index) => row[3] ? [index] : []);
    return chunk;
  }

  function filter(asset, shelf) {
    if (shelf === 'legacy') return asset.legacy;
    if (shelf !== 'all-with-legacy' && asset.legacy) return false;
    return shelf === 'all' || shelf === 'all-with-legacy' || asset.shelves.includes(shelf);
  }

  function rankPart(part, query, phrase, vector, limit) {
    const lexical = new Map();
    for (const word of query) {
      const postings = Object.hasOwn(part.postings, word) ? part.postings[word] : [];
      for (const post of postings) {
        const index = post >>> 4, score = post & 15;
        const stats = lexical.get(index) || [0, 0];
        stats[0]++;
        stats[1] += score;
        lexical.set(index, stats);
      }
    }
    const found = [];
    const candidates = vector ? new Set([...lexical.keys(), ...part.vectors]) : lexical.keys();
    for (const index of candidates) {
      const row = part.records[index];
      const stats = lexical.get(index);
      if (!stats && !(vector && row[3])) continue;
      let similarity = 0;
      if (vector && row[3]) {
        const packed = bytes(row[3]);
        const signed = new Int8Array(packed.buffer);
        for (let col = 0; col < vector.length; col++) similarity += vector[col] * signed[col];
      }
      if (!stats && similarity < 0.64) continue;
      const title = normalize(row[0]);
      const exact = title === phrase, phraseHit = !exact && title.includes(phrase);
      const score = (exact ? 145 : phraseHit ? 29 : 0) +
        (stats ? 12 + 44 * (stats[0] / query.length) ** 2 + 7 * stats[1] / query.length : 0) +
        65 * Math.max(0, similarity - 0.48) - (row[4] ? 17 : 0);
      found.push({row, index, score});
    }
    return found.sort((a, b) => b.score - a.score || a.index - b.index).slice(0, limit);
  }

  function result(asset, hit, part) {
    const [title, locator, lead] = hit.row;
    const archive = asset.format === 'zim';
    const destination = asset.destination;
    const href = destination.split('/').map(encodeURIComponent).join('/') +
      (asset.format === 'pdf' ? '#page=' + locator : '');
    return {score: hit.score, record: {id: asset.id + ':' + part + ':' + hit.index,
      asset_id: asset.id, title, description: lead, source_title: asset.title, href, destination,
      kind: archive ? 'article' : 'section', reader_required: archive,
      location: archive ? 'Archive path: ' + locator : asset.format === 'pdf' ? 'Page ' + locator : 'HTML',
      license: asset.license, attribution: asset.attribution}};
  }

  async function search(selection, encodeQuery, readPart, text, shelf = 'all', limit = 30, cancelled = () => false) {
    const query = terms(text), phrase = normalize(text);
    if (query.length > 32) throw Error('Use at most 32 different search words.');
    if (!query.length) return [];
    const vector = encodeQuery(text);
    let matches = [];
    for (const asset of selection.sources) {
      if (!filter(asset, shelf)) continue;
      for (let number = 0; number < asset.parts.length; number++) {
        if (cancelled()) return [];
        const part = asset.parts[number];
        if (!(vector && part.vectors) && !mightMatch(atob(part.bloom), query)) continue;
        const chunk = await readPart(asset.sha256, number);
        matches.push(...rankPart(chunk, query, phrase, vector, limit).map(hit => result(asset, hit, number)));
        matches.sort(order);
        if (matches.length > limit * 4) matches.length = limit * 4;
      }
    }
    return topResults(matches, limit);
  }

  const order = (a, b) => b.score - a.score || a.record.title.localeCompare(b.record.title, 'en') ||
    a.record.id.localeCompare(b.record.id, 'en');

  function topResults(matches, limit) {
    const seen = new Set();
    return matches.sort(order).filter(({record}) => {
      // Preserve distinct sections and collapse equivalent spellings within the same archive.
      const key = record.asset_id + '\0' + (record.kind === 'article' ? normalize(record.title) : record.href);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, limit);
  }

  function classic(script, selection, table) {
    if (selection.version !== 1 || !Array.isArray(selection.sources)) throw Error('Invalid search selection');
    const encodeQuery = model(table);
    // Each page owns one script callback at a time. New searches can cancel reads
    // between chunks, so they cannot replace callbacks for an active script.
    let queue = Promise.resolve();
    const readPart = (digest, number) => {
      if (!/^[a-f0-9]{64}$/.test(digest) || !Number.isInteger(number) || number < 0 || number >= 100000)
        return Promise.reject(Error('Invalid search shard'));
      const task = queue.then(async () => {
        let data;
        root.OWLShardPart = value => { data = value; };
        try {
          await script('SEARCH/sources/' + digest + '/' + String(number).padStart(5, '0') + '.js');
          if (!data || data[0] !== digest || data[1] !== number) throw Error('Search shard identity differs');
          return await unpack(data[2]);
        } finally {
          delete root.OWLShardPart;
        }
      });
      queue = task.catch(() => {});
      return task;
    };
    return (text, shelf, limit, cancelled) => search(selection, encodeQuery, readPart, text, shelf, limit, cancelled);
  }

  const api = {classic, model, search, terms, unpack, rankPart, normalize, mightMatch, result, order, topResults};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.OWLShardRank = api;
})(globalThis);
