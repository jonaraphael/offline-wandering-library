/* Offline all-MiniLM-L6-v2 second-stage ranking over a bounded shortlist. */
(function (root) {
  'use strict';

  function tokens(text, vocab) {
    const cleaned = text.replace(/\s/gu, ' ').replace(/[\p{Cc}\p{Cf}\uFFFD]/gu, '')
      .replace(/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/gu, ' $& ')
      .toLowerCase().normalize('NFD').replace(/\p{Mn}/gu, '');
    const words = cleaned.match(/[^\s\p{P}!-/:-@\[-\x60{-~]+|[\p{P}!-/:-@\[-\x60{-~]/gu) || [];
    const output = [101];
    for (const word of words) {
      const ids = [];
      if (word.length <= 100) {
        for (let start = 0; start < word.length;) {
          let end = word.length;
          for (; end > start; end--) {
            const id = vocab.get((start ? '##' : '') + word.slice(start, end));
            if (id !== undefined) {
              ids.push(id);
              break;
            }
          }
          if (end === start) {
            ids.length = 0;
            break;
          }
          start = end;
        }
      }
      output.push(...(ids.length ? ids : [100]));
      if (output.length >= 63) break;
    }
    return [...output.slice(0, 63), 102];
  }

  function concat(parts) {
    const data = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
    let offset = 0;
    for (const part of parts) {
      data.set(part, offset);
      offset += part.length;
    }
    return data;
  }

  async function open(script) {
    const prefix = 'SEARCH/transformer/';
    const weights = {model: [], wasm: [], glue: []};
    let header;
    root.OWLTransformer = data => { header = data; };
    root.OWLTransformerPart = ([kind, slot, data]) => {
      if (Object.hasOwn(weights, kind) && Number.isInteger(slot) && slot >= 0 && slot < 32) {
        weights[kind][slot] = root.OWLShardRank.bytes(data);
      }
    };
    try {
      await script(prefix + 'assets.js');
      if (!Array.isArray(header?.parts) || !header.parts.every(name => /^(?:model|wasm|glue)-\d{2}\.js$/.test(name))) {
        throw Error('Invalid local transformer manifest');
      }
      const loads = await Promise.allSettled([...header.parts, 'ort.wasm.min.js'].map(name => script(prefix + name)));
      if (loads.some(result => result.status === 'rejected')) throw Error('Local transformer assets could not load');
    } finally {
      delete root.OWLTransformerPart;
      delete root.OWLTransformer;
    }
    const ort = root.ort;
    ort.env.wasm.numThreads = 1;
    ort.env.wasm.proxy = false;
    ort.env.wasm.wasmBinary = concat(weights.wasm).buffer;
    const glue = URL.createObjectURL(new Blob(weights.glue, {type: 'text/javascript'}));
    ort.env.wasm.wasmPaths = {mjs: glue};
    try {
      const active = await ort.InferenceSession.create(concat(weights.model), {executionProviders: ['wasm']});
      ort.env.wasm.wasmBinary = undefined;
      return {active, ort, vocab: new Map(Object.entries(header.vocab))};
    } finally {
      URL.revokeObjectURL(glue);
    }
  }

  async function encode(model, texts) {
    const rows = texts.map(text => tokens(text, model.vocab));
    const width = Math.max(...rows.map(row => row.length));
    const shape = [rows.length, width];
    const ids = new BigInt64Array(rows.length * width);
    const mask = new BigInt64Array(ids.length);
    for (const [row, words] of rows.entries()) {
      ids.set(BigInt64Array.from(words, BigInt), row * width);
      mask.fill(1n, row * width, row * width + words.length);
    }
    const tensor = values => new model.ort.Tensor('int64', values, shape);
    const result = await model.active.run({input_ids: tensor(ids), attention_mask: tensor(mask),
      token_type_ids: tensor(new BigInt64Array(ids.length))});
    const output = result.last_hidden_state;
    const dimensions = output.dims[2];
    return rows.map((words, row) => {
      const vector = new Float32Array(dimensions);
      for (let word = 0; word < words.length; word++) {
        const start = (row * width + word) * dimensions;
        for (let i = 0; i < dimensions; i++) vector[i] += output.data[start + i];
      }
      const norm = Math.hypot(...vector);
      return vector.map(value => value / norm);
    });
  }

  function create(script) {
    let ready, queue = Promise.resolve();
    return (text, hits, cancelled) => {
      const task = queue.then(async () => {
        if (cancelled()) return [];
        const model = await (ready ??= open(script).catch(error => { ready = undefined; throw error; }));
        if (cancelled()) return [];
        const [query] = await encode(model, [text]);
        const scores = [];
        const candidates = hits.slice(0, 50);
        for (let offset = 0; offset < candidates.length; offset += 8) {
          if (cancelled()) return [];
          const batch = candidates.slice(offset, offset + 8);
          const passages = await encode(model, batch.map(({record}) =>
            [record.title, record.description || record.source_title].join('. ')));
          for (const [i, vector] of passages.entries()) {
            const similarity = vector.reduce((sum, value, j) => sum + value * query[j], 0);
            const candidate = batch[i];
            scores.push({...candidate, score: candidate.score + 25 * (similarity - 0.35)});
          }
        }
        return scores;
      });
      queue = task.catch(() => {});
      return task;
    };
  }
  root.OWLReranker = {create};
})(globalThis);
