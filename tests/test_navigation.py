"""Exercise the generated reader and its complete static layer."""
from html.parser import HTMLParser
import json
from pathlib import Path
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
        return generate_navigation(self.target, assets, {'assets': assets, **inventory},
                                   {'generated_files': ['SEARCH/manifest.js', 'SEARCH/search.js']}, write=False)

    def test_static_page_folds_chapters_and_lists_precise_escaped_locations(self):
        chapters = [self.asset(f'chapter{i}', f'Field Guide — {i} Work', f'BOOKS/GUIDE/{i}.pdf')
                    for i in (10, 3, 2)]
        water = self.asset('water', 'Water & <Guide>', 'CRITICAL/WATER/water #1.pdf')
        pages = self.generate([water, *chapters])
        self.assertEqual(set(pages), set(GENERATED_PATHS))
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
        self.assertNotIn('Field Guide', pages['INDEX/home.js'])
        book, = [row for row in reader_data(pages['INDEX/c-other.js'], 'other') if row.get('chapters')]
        self.assertEqual(book['kind'], 'Book, 3 chapters')
        self.assertEqual([row['title'] for row in book['chapters']], ['2 Work', '3 Work', '10 Work'])
        self.assertIn('href="CRITICAL/WATER/water%20%231.pdf"', pages['INVENTORY.html'])
        validate_links(self.target, {**pages, 'INVENTORY.json': '', 'SEARCH/manifest.js': '', 'SEARCH/search.js': ''})

    def test_emergency_uses_article_route_or_reports_the_missing_file(self):
        wiki = self.asset('wikimed_en', 'Medical encyclopedia', 'ZIM/medicine.zim', format='zim')
        pages = self.generate([wiki])
        home = reader_data(pages['INDEX/home.js'], 'home')
        task = next(task for task in home['tasks'] if task['task'] == 'Care for burns')
        self.assertEqual(task['articles'], ['Burn'])
        self.assertEqual(task['format'], 'zim')
        self.assertIn('Look up Burn in Kiwix', pages['START_HERE.html'])
        self.assertEqual(len(home['tasks']), len(layout()['tasks']))
        self.assertTrue(all('path' not in task for task in
                            reader_data(self.generate([])['INDEX/home.js'], 'home')['tasks']))

    def test_inventory_reports_missing_and_software_without_counting_software_as_documents(self):
        app = self.asset('kiwix_android', 'Kiwix', 'SOFTWARE/ANDROID/kiwix.apk', format='apk')
        pages = self.generate([app], content_complete=False,
                              unresolved=[{'id': 'missing', 'title': '<Missing>', 'reason': 'Unavailable'}])
        home = reader_data(pages['INDEX/home.js'], 'home')
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
            written = generate_navigation(self.target, assets, {'assets': assets},
                                          {'generated_files': ['SEARCH/manifest.js', 'SEARCH/search.js']})
            self.assertEqual(expected, {key: managed_path(self.target, key).read_text() for key in written})
        self.assertEqual(self.target.joinpath('personal.txt').read_text(), 'Keep this')

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
