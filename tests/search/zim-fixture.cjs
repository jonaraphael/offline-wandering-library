
const main = `<!doctype html><html lang="en"><head><title>Fixture CPR</title>
<link rel="stylesheet" href="_assets/style.css">
<meta http-equiv="refresh" content="1; url=https://example.invalid/refresh">
<base href="https://example.invalid/"><script src="https://example.invalid/script"></script>
</head><body class="article"><h1>Fixture CPR</h1><div class="illustration"></div>
<p>First-page marker. The article and illustration are stored in a split archive.</p>
<img src="_assets/marker.svg" srcset="_assets/marker.svg 1x" width="28" height="12" onload="parent.unsafe=true">
<iframe src="https://example.invalid/frame"></iframe><form action="https://example.invalid/form"><button>Submit</button></form>
<a href="Second">Next article</a><a href="#target">Jump to section</a>
<a href="https://example.invalid/outside">Outside link</a>
<div style="height:1400px"></div><h2 id="target">Section target</h2><div style="height:600px"></div></body></html>`;
const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="12"><rect width="28" height="12" fill="teal"/></svg>';

// Inert markers make removal observable without executable test code.
const markupCases = {
  math: '<math><mtext><table><mglyph><style><img src=x onerror="/*owl-fixture*/"></style></mglyph></table></mtext></math>',
  svg: '<svg><style><img onerror="/*owl-fixture*/"></style></svg>',
  noscript: '<noscript><p title="</noscript><img onerror=\'/*owl-fixture*/\'>">',
  href: '<a href="javascript:/*owl-fixture*/">Label</a>',
  xlink: '<svg><a xlink:href="javascript:/*owl-fixture*/"><text>Label</text></a></svg>',
  formaction: '<input formaction="javascript:/*owl-fixture*/">',
  animation: '<svg><animate attributeName="href" values="javascript:/*owl-fixture*/"></animate></svg>',
  toggle: '<details ontoggle="/*owl-fixture*/"><summary>Label</summary></details>',
  media: '<video><source onerror="/*owl-fixture*/"></video>',
};

async function inspectMarkup(page, sandbox) {
  return page.evaluate(async ({cases, sandbox}) => {
    const results = {};
    for (const [name, markup] of Object.entries(cases)) {
      const html = '<h1>Clean control</h1><a href="Second">Keep this link</a>' + markup;
      const zim = {minor: 1, get: async () => null, blob: async () => new Blob([html])};
      const entry = {path: 'First', title: 'Fixture', mime: 'text/html'};
      const prepared = await OWLZimArticle.prepare(zim, entry, [], new AbortController().signal);
      const frame = document.createElement('iframe');
      frame.sandbox = sandbox;
      frame.hidden = true;
      await new Promise(resolve => {
        frame.onload = resolve;
        frame.srcdoc = prepared.html;
        document.body.append(frame);
      });
      const doc = frame.contentDocument;
      const active = [...doc.querySelectorAll('*')].flatMap(node => [...node.attributes]
        .filter(({name, value}) => /^on/i.test(name) || /javascript:/i.test(value) &&
          /^(?:href|xlink:href|formaction|values)$/i.test(name)).map(({name}) => name));
      results[name] = {active, discarded: doc.querySelectorAll('animate, noscript, script, input').length,
        control: doc.querySelector('h1')?.textContent, link: doc.querySelector('a')?.getAttribute('href')};
      frame.remove();
    }
    return results;
  }, {cases: markupCases, sandbox});
}

// Generate a small range-readable archive, including header and index boundary cases.
function makeZim({legacy = false, compression = 1, cycle = false, titleListing = !legacy, compactTitle = false,
  scripted = false, noMain = false, longPath = false, zstd = input => {
    const header = Buffer.alloc(8);
    header.writeUInt32LE(0xfd2fb528);
    header[4] = 0x60;
    header.writeUInt16LE(input.length - 256, 5);
    const block = Buffer.alloc(3);
    block.writeUIntLE((input.length << 3) | 1, 0, 3);
    return Buffer.concat([header.subarray(0, 7), block, input]);
  }} = {}) {
  const ns = legacy ? 'A' : 'C';
  const mimes = ['text/html', 'text/css', 'image/svg+xml', 'application/octet-stream'];
  const mimeTable = Buffer.from(mimes.join('\0') + '\0\0');
  const page = scripted ? '<title>Script archive</title><script src="app.js"></script><div id="app"></div>' : main;
  const mainPath = 'Cardiopulmonary_resuscitation';
  const img = legacy ? 'I' : ns, css = legacy ? '-' : ns;
  const entries = [
    {ns, path: mainPath, title: 'Fixture CPR', mime: 0, data: page},
    {ns, path: 'Redirect', redirect: cycle ? 'Redirect' : mainPath},
    {ns, path: 'Second', title: 'Second article', mime: 0, data: '<h1>Second article</h1><p>Second-page marker.</p>'},
    {ns: css, path: '_assets/style.css', mime: 1, data: '@import "imported.css"; .illustration { background-image: url(marker.svg); height: 12px }'},
    {ns: css, path: '_assets/imported.css', mime: 1, data: 'h1 { color: rgb(21, 80, 90) }'},
    {ns: img, path: '_assets/marker.svg', mime: 2, data: svg},
    {ns: 'W', path: 'mainPage', redirect: mainPath},
  ];
  if (longPath) entries.push({ns, path: 'a'.repeat(2200), title: 'Long path', mime: 0, data: page});
  if (titleListing) entries.push({ns: 'X', path: 'listing/titleOrdered/v1', mime: 3});
  entries.sort((a, b) => Buffer.compare(Buffer.from(a.ns + a.path), Buffer.from(b.ns + b.path)));
  const indexes = entries.map((_, i) => i);
  const byTitle = indexes.sort((a, b) => Buffer.compare(Buffer.from(entries[a].ns + (entries[a].title || entries[a].path)),
    Buffer.from(entries[b].ns + (entries[b].title || entries[b].path))));
  const table = values => {
    const result = Buffer.alloc(values.length * 4);
    values.forEach((entry, i) => result.writeUInt32LE(entry, i * 4));
    return result;
  };
  if (titleListing) entries.find(entry => entry.ns === 'X').data =
    table(byTitle.filter(i => entries[i].ns === ns));
  const titleTable = compactTitle ? Buffer.alloc(0) : table(byTitle);
  const blobs = entries.filter(entry => !entry.redirect).map(entry => Buffer.from(entry.data));
  let offset = (blobs.length + 1) * 4;
  const offsets = blobs.map(blob => {
    const prev = offset;
    offset += blob.length;
    return prev;
  });
  const raw = Buffer.concat([table([...offsets, offset]), ...blobs]);
  const cluster = Buffer.concat([Buffer.from([compression]), compression === 5 ? zstd(raw) : raw]);
  let count = 0;
  const dirents = entries.map(entry => {
    const data = Buffer.alloc(entry.redirect ? 12 : 16);
    data.writeUInt16LE(entry.redirect ? 0xffff : entry.mime);
    data[3] = entry.ns.charCodeAt(0);
    if (entry.redirect) data.writeUInt32LE(entries.findIndex(row => row.path === entry.redirect), 8);
    else data.writeUInt32LE(count++, 12);
    return Buffer.concat([data, Buffer.from(entry.path + '\0' + (entry.title || '') + '\0')]);
  });
  const header = Buffer.alloc(80);
  const paths = Buffer.alloc(entries.length * 8);
  const clusters = Buffer.alloc(8);
  const clusterStart = header.length + mimeTable.length + paths.length + titleTable.length + clusters.length +
    dirents.reduce((sum, part) => sum + part.length, 0);
  clusters.writeBigUInt64LE(BigInt(clusterStart));
  let pointer = clusterStart - dirents.reduce((sum, part) => sum + part.length, 0);
  dirents.forEach((dirent, i) => {
    paths.writeBigUInt64LE(BigInt(pointer), i * 8);
    pointer += dirent.length;
  });
  const pathTableOffset = header.length + mimeTable.length;
  header.writeUInt32LE(72173914);
  header.writeUInt16LE(6, 4);
  header.writeUInt16LE(legacy ? 0 : compactTitle ? 3 : 1, 6);
  header.writeUInt32LE(entries.length, 24);
  header.writeUInt32LE(1, 28);
  header.writeBigUInt64LE(BigInt(pathTableOffset), 32);
  header.writeBigUInt64LE(compactTitle ? (1n << 64n) - 1n : BigInt(pathTableOffset + paths.length), 40);
  header.writeBigUInt64LE(BigInt(pathTableOffset + paths.length + titleTable.length), 48);
  header.writeBigUInt64LE(80n, 56);
  header.writeUInt32LE(noMain ? 0xffffffff : entries.findIndex(entry => entry.path === 'Redirect'), 64);
  header.writeUInt32LE(0xffffffff, 68);
  header.writeBigUInt64LE(BigInt(clusterStart + cluster.length), 72);
  return Buffer.concat([header, mimeTable, paths, titleTable, clusters, ...dirents, cluster, Buffer.alloc(16)]);
}

module.exports = {makeZim, inspectMarkup, markupCases};
