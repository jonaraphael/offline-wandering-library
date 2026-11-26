const {test} = require('node:test');
const assert = require('node:assert/strict');
const {resolve} = require('node:path');
const {inspectMarkup, markupCases} = require('./zim-fixture.cjs');

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
    } finally {
      await browser.close();
    }
  });
}
