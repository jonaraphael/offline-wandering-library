"""The hosted builder page has no embedded model element; its engine must still load."""
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from owl.selector import make_model, render_selector
from scripts.build_pages import connect_origins, version_module_imports

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node required for selector UI checks')
class PagesPageTests(unittest.TestCase):
    def test_hosted_page_defines_planner_without_embedded_model(self):
        model = make_model(ROOT / 'catalog/library.yaml', ROOT / 'profiles', ROOT / 'catalog/resources.yaml')
        origins = connect_origins(["https://provider.test/archive", "https://relay.test:8443/assets/id",
                                   "./search/", "https://provider.test/reader"])
        html = render_selector(model, pages=True, version="commit", connect_origins=origins)
        self.assertNotIn('id="owl-model"', html)
        self.assertEqual(html.count("<script"), 1)
        self.assertIn('<script type="module" src="./pages-entry.mjs?v=commit"></script>', html)
        self.assertIn("script-src 'self';", html)
        self.assertIn("connect-src 'self' https://provider.test https://relay.test:8443;", html)
        self.assertNotIn("connect-src 'self' https:;", html)
        templates = ROOT / "src/owl/templates"
        entry = version_module_imports((templates / "pages-entry.mjs").read_text(encoding="utf-8"), "commit")
        for module in ("selector.js", "selector-map.js", "builder-ui.mjs"):
            self.assertIn(f'"./{module}?v=commit"', entry)
        code = """await import(process.argv[1]); await import(process.argv[2]);
if (!globalThis.OWLPlanner || !globalThis.OWLManage) throw Error('Planner engine did not load');"""
        result = subprocess.run([shutil.which('node'), '--input-type=module', '--eval', code,
                                 *((templates / name).as_uri() for name in ("selector.js", "selector-map.js"))],
                                encoding='utf-8', capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_build_requires_relay(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/build_pages.py"), "--fetch-mirrors"],
                                encoding="utf-8", capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--fetch-mirrors requires --relay-base", result.stderr)


if __name__ == '__main__':
    unittest.main()
