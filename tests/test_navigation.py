"""Exercise the generated reader and its complete static layer."""
from html.parser import HTMLParser
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile
import unittest

from owl.atlas_build import validate_links
from owl.layout import managed_path
from owl.navigation import GENERATED_PATHS, generate_navigation
from owl.offline_layout import layout
from owl.safety import SafetyError


def reader_data(text, name):
    prefix = 'globalThis.OWLReaderData(' + json.dumps(name) + ','
    assert text.startswith(prefix) and text.endswith(');\n')
    return json.loads(text[len(prefix):-3])


def generation(pages):
    return re.search(r'src="LIBRARY/(INDEX/[a-f0-9]{12})/search\.js"', pages["START_HERE.html"])[1]


def script(pages, file):
    return pages[f"{generation(pages)}/{file}"]


class StaticHTML(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.static = False
        self.text = []
        self.interactive = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == 'main' and dict(attrs).get('class') == 'static':
            self.static = True
        if self.static and tag in {'input', 'button', 'nav', 'details'}:
            self.interactive.append(tag)

    def handle_endtag(self, tag):
        if tag == 'main':
            self.static = False

    def handle_data(self, data):
        if self.static:
            self.text.append(data)


class NavigationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.target = Path(temp.name).resolve() / 'LIBRARY'
        self.target.mkdir()

    def asset(self, identity, title, destination, **extra):
        path = self.target / destination
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'0123456789')
        return {'id': identity, 'title': title, 'destination': destination,
                'format': 'pdf', 'size_bytes': 10, 'license': 'CC BY-SA', **extra}

    def generate(self, assets, **inventory):
        return generate_navigation(self.target, assets, {'assets': assets, **inventory}, {}, write=False)

    def test_static_page_folds_chapters_and_lists_precise_escaped_locations(self):
        chapters = [self.asset(f'chapter{i}', f'Field Guide — {i} Work', f'BOOKS/GUIDE/{i}.pdf')
                    for i in (10, 3, 2)]
        water = self.asset('water', 'Water & <Guide>', 'CRITICAL/WATER/water #1.pdf')
        pages = self.generate([water, *chapters])
        self.assertEqual({path for path in pages if not path.startswith("INDEX/")}, set(GENERATED_PATHS))
        reader = StaticHTML(pages['START_HERE.html'])
        content = ''.join(reader.text)
        self.assertFalse(reader.interactive)
        self.assertIn('Files on this drive are in the LIBRARY folder, grouped by subject.', content)
        self.assertIn('Make drinking water saferLIBRARY/CRITICAL/WATER/water #1.pdf', content)
        self.assertIn('Water & <Guide>', content)
        self.assertEqual(content.count('Field Guide'), 1)
        self.assertIn('LIBRARY/BOOKS/GUIDE/', content)
        self.assertNotIn('/10.pdf', content)
        for device in ('iPhone', 'Android phone', 'Windows PC', 'Mac'):
            self.assertIn(device, content)
        self.assertNotIn('Field Guide', script(pages, 'home.js'))
        book, = [row for row in reader_data(script(pages, 'c-other.js'), 'other') if row.get('chapters')]
        self.assertEqual(book['kind'], 'Book, 3 chapters')
        self.assertEqual([row['title'] for row in book['chapters']], ['2 Work', '3 Work', '10 Work'])
        self.assertIn('href="CRITICAL/WATER/water%20%231.pdf"', pages['INVENTORY.html'])
        validate_links(self.target, {**pages, 'INVENTORY.json': ''})

    def test_emergency_uses_article_route_or_reports_the_missing_file(self):
        wiki = self.asset('wikimed_en', 'Medical encyclopedia', 'ZIM/medicine.zim', format='zim')
        pages = self.generate([wiki])
        home = reader_data(script(pages, 'home.js'), 'home')
        task = next(task for task in home['tasks'] if task['task'] == 'Care for burns')
        self.assertEqual(task['articles'], ['Burn'])
        self.assertEqual(task['format'], 'zim')
        self.assertIn('Look up Burn in Kiwix', pages['START_HERE.html'])
        self.assertEqual(len(home['tasks']), len(layout()['tasks']))
        self.assertTrue(all('path' not in task for task in
                            reader_data(script(self.generate([]), 'home.js'), 'home')['tasks']))

    def test_inventory_reports_missing_and_software_without_counting_software_as_documents(self):
        app = self.asset('kiwix_android', 'Kiwix', 'SOFTWARE/ANDROID/kiwix.apk', format='apk')
        pages = self.generate([app], content_complete=False,
                              unresolved=[{'id': 'missing', 'title': '<Missing>', 'reason': 'Unavailable'}])
        home = reader_data(script(pages, 'home.js'), 'home')
        self.assertEqual(home['searchCount'], 0)
        self.assertEqual(home['stats']['count'], 1)
        self.assertEqual(home['readers'][0]['path'], 'LIBRARY/SOFTWARE/ANDROID/kiwix.apk')
        self.assertIn('This library is incomplete', pages['START_HERE.html'])
        self.assertIn('&lt;Missing&gt;', pages['BUILD_REPORT.html'])
        self.assertIn('Unavailable', pages['BUILD_REPORT.html'])

    def test_generation_is_deterministic_and_leaves_unowned_files_in_place(self):
        self.target.joinpath('personal.txt').write_text('Keep this')
        assets = [self.asset('water', 'Water', 'BOOKS/water.pdf')]
        expected = self.generate(assets)
        for _ in range(2):
            written = generate_navigation(self.target, assets, {'assets': assets}, {})
            self.assertEqual(expected, {key: managed_path(self.target, key).read_text() for key in written})
        self.assertEqual(self.target.joinpath('personal.txt').read_text(), 'Keep this')

    def test_entry_points_to_the_hash_of_the_generation_and_publishes_last(self):
        from owl.atlas_build import write_outputs
        from unittest.mock import patch

        assets = [self.asset('water', 'Water', 'BOOKS/water.pdf')]
        before = self.generate(assets)
        pages = self.generate(assets, syncedAt='2026-02-01T04:05:06Z')
        prefix = generation(pages)
        self.assertNotEqual(prefix, generation(before))
        hashes = [[path.removeprefix(prefix + '/'), sha256(value.encode()).hexdigest()]
                  for path, value in sorted(pages.items()) if path.startswith(prefix + '/')]
        self.assertEqual(prefix, 'INDEX/' + sha256(json.dumps(hashes, separators=(',', ':')).encode()).hexdigest()[:12])
        self.assertEqual(reader_data(script(pages, 'home.js'), 'home')['syncedAt'], '2026-02-01T04:05:06Z')
        with patch('owl.atlas_build.atomic_write') as atomic:
            write_outputs(self.target, pages)
        self.assertEqual(atomic.call_args_list[-1].args[0], self.target.parent / 'START_HERE.html')

    def test_untrusted_paths_are_rejected(self):
        asset = {'id': 'bad', 'title': 'Bad', 'destination': '../personal.pdf', 'format': 'pdf'}
        with self.assertRaises((SafetyError, ValueError)):
            self.generate([asset])

    def test_symlink_directory_cannot_redirect_output(self):
        outside = self.target.parent / 'other'
        outside.mkdir()
        self.target.joinpath('INDEX').symlink_to(outside)
        with self.assertRaises(SafetyError):
            generate_navigation(self.target, [], {}, {})
        self.assertEqual(list(outside.iterdir()), [])
