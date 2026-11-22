"""The hosted builder page has no embedded model element; its engine must still load."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from owl.selector import make_model, render_selector

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node required for selector UI checks')
class PagesPageTests(unittest.TestCase):
    def test_hosted_page_defines_planner_without_embedded_model(self):
        model = make_model(ROOT / 'catalog/library.yaml', ROOT / 'profiles', ROOT / 'catalog/resources.yaml')
        html = render_selector(model, pages=True)
        self.assertNotIn('id="owl-model"', html)
        engine = next(script for script in re.findall(r'<script>([\s\S]*?)</script>', html) if 'OWLPlanner' in script)
        code = (r'''
globalThis.document = {getElementById: () => null};
''' + engine + r'''
if (typeof globalThis.OWLPlanner === 'undefined' && typeof OWLPlanner === 'undefined') throw Error('Planner engine did not load');
''')
        result = subprocess.run([shutil.which('node'), '-e', code], encoding='utf-8', capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
