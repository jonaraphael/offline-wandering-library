const {test} = require('node:test');
const assert = require('node:assert/strict');
const {resolve} = require('node:path');
const {inspectMarkup, markupCases} = require('./zim-fixture.cjs');
const {restoreMediaFallback, hideMainHeading, recoverLayout} = require('../../src/owl/templates/zim-article.js');

const styled = () => ({style: {setProperty(...args) { this.changes.push(args); }, changes: []}});

test('layout recovery restores body children and positioned descendants only after collapse', () => {
  const wrapper = styled(), positioned = styled(), inFlow = styled();
  const doc = {
    body: {children: [wrapper], querySelectorAll: () => [wrapper, positioned, inFlow]},
    defaultView: {getComputedStyle: node => ({position: node === positioned ? 'absolute' : 'relative'})},
  };
  const page = {textLength: 10};
  recoverLayout(doc, page, () => 40);
  assert.deepEqual(wrapper.style.changes, []);
  const heights = [0, 245];
  recoverLayout(doc, page, () => heights.shift());
  const overrides = [['position', 'static', 'important'], ['height', 'auto', 'important'], ['transform', 'none', 'important']];
  assert.deepEqual(wrapper.style.changes, overrides);
  assert.deepEqual(positioned.style.changes, overrides);
  assert.deepEqual(inFlow.style.changes, []);
  assert.deepEqual(heights, []);
});

test('noscript keeps a media alternative and drops a text-only warning', () => {
  for (const media of [null, 'img', 'picture', 'video', 'source']) {
    const discard = {removed: false, remove() { this.removed = true; }};
    const template = {content: {
      querySelectorAll: () => [discard],
      querySelector: selector => selector.split(', ').includes(media) ? {} : null,
    }};
    const warning = 'Enable JavaScript';
    const node = {
      ownerDocument: {createElement: () => template},
      innerHTML: media ? '<' + media + '>' : warning,
      textContent: media ? '' : warning,
      remove() { this.removed = true; },
      replaceWith(content) { this.replacement = content; },
    };
    restoreMediaFallback(node);
    assert.equal(template.innerHTML, node.innerHTML);
    assert.equal(discard.removed, true);
    assert.equal(Boolean(node.removed), !media);
    assert.equal(node.replacement, media ? template.content : undefined);
    const raw = {...node, innerHTML: '&lt;' + media + '&gt;', textContent: node.innerHTML};
    restoreMediaFallback(raw, true);
    assert.equal(template.innerHTML, raw.textContent);
  }
});

test('main heading cleanup hides the leading heading and its subpage trails', () => {
  const heading = styled(), adjacent = styled(), subpage = styled();
  heading.nextElementSibling = adjacent;
  adjacent.matches = selector => selector.includes('.breadcrumb');
  const doc = {querySelector: selector => selector.startsWith('h1') ? heading : subpage};
  hideMainHeading(doc);
  for (const node of [heading, adjacent, subpage]) {
    assert.deepEqual(node.style.changes, [['display', 'none', 'important']]);
  }
});

for (const name of ['chromium', 'firefox', 'webkit']) {
  test(`article markup stabilizes without active attributes in ${name}`, {
    skip: !process.env.OWL_ZIM_BROWSER_TEST && 'Set OWL_ZIM_BROWSER_TEST=1 with Playwright and the three engines installed.',
  }, async () => {
    const browser = await require('playwright-core')[name].launch();
    try {
      const page = await browser.newPage();
      for (const script of ['zim.js', 'zim-article.js']) {
        await page.addScriptTag({path: resolve(__dirname, '../../src/owl/templates', script)});
      }
      const results = await inspectMarkup(page, name === 'webkit' ? 'allow-same-origin allow-scripts' : 'allow-same-origin');
      assert.deepEqual(Object.keys(results), Object.keys(markupCases));
      for (const [specimen, result] of Object.entries(results)) {
        assert.deepEqual(result, {active: [], discarded: 0, control: 'Clean control', link: '#'}, specimen);
      }
      const layout = await page.evaluate(async () => {
        const html = '<noscript>Enable JavaScript</noscript><noscript>&lt;img alt="Escaped image"&gt;</noscript>' +
          '<noscript><img src="missing.svg" alt="Lazy picture"></noscript>' +
          '<style>body > div {display:none}</style><div><a href="Second">Second article</a>' +
          '<a href="https://example.invalid"><img alt="Outside image"></a></div>';
        const zim = {minor: 1, get: async () => null, blob: async () => new Blob([html])};
        const archive = await OWLZimArticle.prepare(zim, {path: 'First', mime: 'text/html', title: 'Fixture'},
          [], new AbortController().signal);
        const doc = new DOMParser().parseFromString(archive.html, 'text/html');
        const media = doc.querySelector('img')?.alt;
        const warning = doc.body.textContent.includes('Enable JavaScript');
        const sizes = [15, 15, 60];
        // Use a live DOM for the layout inspection while controlling the height readings.
        const frame = document.createElement('iframe');
        await new Promise(resolve => {
          frame.onload = resolve;
          frame.srcdoc = archive.html;
          document.body.append(frame);
        });
        const rendered = frame.contentDocument;
        OWLZimArticle.recoverLayout(rendered, archive, () => sizes.shift());
        const links = [...rendered.querySelectorAll('li a')].map(link =>
          [link.textContent, archive.links.get(link.dataset.owlLink), link.getAttribute('href')]);
        frame.remove();
        return {media, warning, sizes, links};
      });
      assert.deepEqual(layout, {media: 'Lazy picture', warning: false, sizes: [], links: [
        ['Second article', {path: 'Second', ns: 'C', query: '', fragment: ''}, '#'],
        ['Outside image', {external: 'https://example.invalid/'}, 'https://example.invalid/'],
      ]});
    } finally {
      await browser.close();
    }
  });
}
