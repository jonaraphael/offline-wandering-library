/* Term postings and binary-code partitions, read through classic local scripts. */
(function (root) {
  'use strict';

  function termBucket(term) {
    let hash = 2166136261;
    for (let i = 0; i < term.length; i++) hash = Math.imul(hash ^ term.charCodeAt(i), 16777619);
    return (hash >>> 24).toString(16).padStart(2, '0');
  }

  function binarySearch(rows, target) {
    let lower = 0, upper = rows.length;
    while (lower < upper) {
      const middle = (lower + upper) >>> 1;
      if (rows[middle][0] < target) lower = middle + 1;
      else upper = middle;
    }
    return rows[lower]?.[0] === target ? rows[lower] : undefined;
  }

  function* postingValues(bytes) {
    let previous = 0, value = 0, shift = 0;
    for (const byte of bytes) {
      value += (byte & 127) * 2 ** shift;
      if (byte & 128) {
        shift += 7;
        if (shift > 28) throw Error('Invalid lexical posting');
      } else {
        previous += value;
        yield previous;
        value = shift = 0;
      }
    }
    if (shift) throw Error('Incomplete lexical posting');
  }

  function vectorPartition(code) {
    return (code[0] & 1) | (code[5] & 2) | (code[11] & 4) | (code[19] & 8) | (code[28] & 16);
  }

  async function readTerms(index, read, terms, decode) {
    const dictionaries = new Map(), blocks = new Map();
    async function cached(cache, path) {
      if (!cache.has(path)) cache.set(path, read(path));
      return cache.get(path);
    }
    return Promise.all(terms.map(async term => {
      const bucket = termBucket(term);
      if (!Object.hasOwn(index.terms, bucket)) return [];
      const ranges = index.terms[bucket];
      let first = 0, last = ranges.length;
      while (first < last) {
        const middle = (first + last) >>> 1;
        if (ranges[middle] <= term) first = middle + 1;
        else last = middle;
      }
      if (!first) return [];
      const dictionary = await cached(dictionaries, 'd/' + bucket + '-' + (first - 1) + '.js');
      const found = binarySearch(dictionary, term);
      if (!found) return [];
      const [, start, count, key] = found;
      return Promise.all(Array.from({length: count}, async (_, i) => {
        const block = await cached(blocks, 'p/' + bucket + '-' + (start + i) + '.js');
        if (typeof block[key] !== 'string') throw Error('Search postings do not match their dictionary');
        return decode(block[key]);
      }));
    }));
  }

  async function candidateParts(index, read, query, eligible, rank, cancelled) {
    const readBytes = rank.bytes;
    const terms = rank.lookupTerms(query);
    const lists = await readTerms(index, read, terms, readBytes);
    if (cancelled()) return [];
    const priorities = new Float32Array(index.parts.length);
    const selected = Uint8Array.from(index.parts, eligible);
    // Pack the primary hit count and sum of field weights in one word per row.
    const stats = new Uint16Array(index.rowCount);
    for (const [termIndex, blocks] of lists.entries()) {
      const primary = query.primary.has(terms[termIndex]);
      for (const block of blocks) {
        for (const post of postingValues(block)) {
          const row = post >>> 4;
          if (row >= index.rowCount) throw Error('Posting points outside the search index');
          if (primary) stats[row] += 512 + (post & 15);
          else if (!stats[row]) stats[row] = 1;
        }
      }
    }
    for (const [part, {start}] of index.parts.entries()) {
      if (!selected[part]) continue;
      const end = index.parts[part + 1]?.start ?? index.rowCount;
      for (let row = start; row < end; row++) {
        const packed = stats[row];
        if (!packed) continue;
        const coverage = (packed >>> 9) / query.query.length;
        const strength = (packed & 511) / query.query.length;
        const lexical = 12 + 70 * coverage ** 2 + 6 * strength;
        // The final emergency score caps literal-word evidence to make room
        // for concept support and relevant critical references.
        const score = query.emergency ? Math.min(48, lexical) : lexical;
        if (score > priorities[part]) priorities[part] = score;
      }
    }

    if (query.vector && !query.emergency) {
      const close = vectorPartition(query.vector.signs);
      const costs = [[0, 0], [5, 1], [11, 2], [19, 3], [28, 4]].map(([byte, bit]) =>
        Math.abs(query.vector.scores[byte * 256 + (1 << bit)] - query.vector.scores[byte * 256]));
      const distance = partition => costs.reduce((sum, cost, bit) =>
        sum + (partition & (1 << bit) ? cost : 0), 0);
      const partitions = index.vectors.map((count, partition) => ({count, partition, cost: distance(close ^ partition)}))
        .filter(({count}) => count).sort((a, b) => a.cost - b.cost).slice(0, 5);
      for (const {count, partition} of partitions) {
        for (let block = 0; block < count; block++) {
          if (cancelled()) return [];
          const data = readBytes(await read('v/' + partition + '-' + block + '.js'));
          if (data.length % 36) throw Error('Invalid binary code block');
          const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
          let part = 0;
          for (let offset = 0; offset < data.length; offset += 36) {
            const row = view.getUint32(offset, true);
            if (row >= index.rowCount) throw Error('Vector points outside the search index');
            while (index.parts[part + 1]?.start <= row) part++;
            if (!selected[part]) continue;
            const similarity = rank.vectorScore(query.vector, data.subarray(offset + 4, offset + 36), false);
            if (similarity < 0.37) continue;
            const score = 19 + 160 * (similarity - 0.24);
            if (score > priorities[part]) priorities[part] = score;
          }
        }
      }
    }
    return priorities;
  }

  async function search(index, read, selection, encode, readPart, text, shelf = 'all', limit = 30,
                        cancelled = () => false, onProgress, recordBudget = Infinity) {
    const rank = root.OWLShardRank;
    const query = rank.prepareQuery(text, encode);
    if (!query.query.length || cancelled()) return [];
    const eligible = part => part.users.some(([source]) => rank.filter(selection.sources[source], shelf));
    const priorities = await candidateParts(index, read, query, eligible, rank, cancelled);
    if (cancelled()) return [];
    // Use the existing source priors and exact-title signatures for ties between
    // blocks. Signatures order reads without adding unverified posting hits.
    const ranks = rank.rankedQueue(selection, query, shelf);
    const order = new Map(ranks.map(({asset, number, score}) =>
      [asset.id + ':' + number, score]));
    const queue = index.parts.flatMap((part, i) => {
      if (!priorities[i]) return [];
      const users = part.users.filter(([source]) => rank.filter(selection.sources[source], shelf));
      const affinity = Math.max(0, ...users.map(([source, number]) =>
        order.get(selection.sources[source].id + ':' + number) || 0));
      return [{part, users, score: priorities[i] + affinity * (query.emergency ? 6 : 2)}];
    }).sort((a, b) => b.score - a.score);
    const hits = [];
    let last = -Infinity;
    for (const {part, users} of queue) {
      if (cancelled()) return [];
      const bytes = part.bytes || 200_000;
      if (bytes > recordBudget) continue;
      recordBudget -= bytes;
      const explicit = part.path.startsWith('chunks/') ? part.path : undefined;
      const contents = await readPart(part.pool, part.offset, rank.lookupTerms(query), explicit);
      for (const [source, number] of users) {
        const asset = selection.sources[source];
        hits.push(...rank.rankPart(contents, query, asset, limit).map(hit => rank.result(asset, hit, number)));
        rank.retainCandidates(hits, limit * 4);
      }
      if (hits.length && onProgress && performance.now() - last >= 150) {
        onProgress(rank.topResults(hits, limit));
        last = performance.now();
      }
    }
    return rank.topResults(hits, limit);
  }

  const api = {termBucket, postingValues, vectorPartition, readTerms, search};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.OWLQueryIndex = api;
})(globalThis);
