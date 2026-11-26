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
        self.folded = []
        self.depth = 0
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == 'main' and dict(attrs).get('class') == 'static':
            self.static = True
        if self.static and tag in {'input', 'button', 'nav'}:
            self.interactive.append(tag)
        if self.static and tag == 'details':
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == 'main':
            self.static = False
        if self.static and tag == 'details':
            self.depth -= 1

    def handle_data(self, data):
        if self.static:
            (self.folded if self.depth else self.text).append(data)


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
        self.assertIn('How to open a book', content)
        self.assertIn('Make drinking water saferWater & <Guide>LIBRARY › CRITICAL › WATER › water #1.pdf', content)
        self.assertIn('<a href="LIBRARY/CRITICAL/WATER/water%20%231.pdf">Make drinking water safer</a>', pages['START_HERE.html'])
        self.assertEqual(content.count('Field Guide'), 1)
        self.assertIn('Book, 3 chaptersLIBRARY › BOOKS › GUIDE', content)
        self.assertNotIn('10.pdf', content)
        # Chapters are listed in reading order with their file names, folded away until asked for.
        self.assertEqual(''.join(reader.folded), 'Show chapters2 Work2.pdf3 Work3.pdf10 Work10.pdf')
        # Reader-app help appears only on a drive that holds an encyclopedia.
        self.assertNotIn('Android phone', content)
        self.assertNotIn('id="kiwix"', pages['START_HERE.html'])
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
        content = ''.join(StaticHTML(pages['START_HERE.html']).text)
        self.assertIn('Care for burnsMedical encyclopedia · Look up Burn in KiwixLIBRARY › ZIM › medicine.zim', content)
        for device in ('iPhone', 'Android phone'):
            self.assertIn(device, content)
        # Computers read encyclopedias in the page; the static page sends them there.
        self.assertNotIn('Windows PC', content)
        self.assertIn('On a computer, open START_HERE.html in a web browser.', content)
        self.assertEqual(len(home['tasks']), len(layout()['tasks']))
        self.assertTrue(all('path' not in task for task in
                            reader_data(script(self.generate([]), 'home.js'), 'home')['tasks']))

    def test_urgent_row_names_the_page_and_tiles_link_to_their_category(self):
        aid = self.asset('hesperian_en_wtnd_2025_10', 'First aid chapter', 'CRITICAL/MEDICAL/aid.pdf')
        start = self.generate([aid])['START_HERE.html']
        self.assertIn('<a href="LIBRARY/CRITICAL/MEDICAL/aid.pdf#page=6">Stop severe bleeding</a></b>'
                      '<small>First aid chapter · page 6</small>', start)
        self.assertIn('<a href="LIBRARY/CRITICAL/MEDICAL/aid.pdf">Care for burns</a></b><small>First aid chapter</small>', start)
        self.assertIn('<b>Make drinking water safer</b><small>No guide on this drive.</small></div>', start)
        tile = re.search(r'<a class="tile" href="#(c-[a-z]+)"', start)
        self.assertIsNotNone(tile)
        self.assertIn(f'<section class="shelf" id="{tile[1]}"', start)
        self.assertIn('id="top"', start)

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
            self.assertEqual(expected, {key: managed_path(self.target, key).read_text(encoding='utf-8') for key in written})
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
