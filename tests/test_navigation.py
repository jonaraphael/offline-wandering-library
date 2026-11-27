"""Exercise the generated reader and its complete static layer."""
from html.parser import HTMLParser
from io import BytesIO

from pypdf import PdfReader
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
import unittest

from owl.atlas_build import validate_links
from owl.layout import PHONE_CATALOG, managed_path
from owl.navigation import GENERATED_PATHS, generate_navigation
from owl.offline_layout import layout
from owl.safety import SafetyError
from owl.search_shards import output_bytes


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
        self.disclosures = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == 'main' and dict(attrs).get('class') == 'static':
            self.static = True
        if self.static and tag in {'input', 'button', 'nav'}:
            self.interactive.append(tag)
        if self.static and tag == 'details':
            self.disclosures.append(dict(attrs).get("class"))

    def handle_endtag(self, tag):
        if tag == 'main':
            self.static = False
        if self.static and tag == 'details':
            self.disclosures.pop()

    def handle_data(self, data):
        if self.static:
            (self.folded if None in self.disclosures else self.text).append(data)


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
        self.assertIn('Make drinking water saferWater & <Guide>LIBRARY › CRITICAL › WATER', content)
        self.assertIn('<span class="filename">water #1.pdf</span>', pages['START_HERE.html'])
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

    def phone_pages(self, pages):
        """Each catalog page as its text and its links: the URL, or the number of the page a jump lands on."""
        pdf = PdfReader(BytesIO(pages[PHONE_CATALOG]), strict=True)
        numbers = {page.indirect_reference.idnum: index + 1 for index, page in enumerate(pdf.pages)}
        result = []
        for page in pdf.pages:
            links = []
            for ref in page.annotations or []:
                note = ref.get_object()
                if "/A" in note:
                    links.append(str(note["/A"]["/URI"]))
                else:
                    dest = note["/Dest"]
                    dest = dest if isinstance(dest, list) else pdf.named_destinations[str(dest)].dest_array
                    links.append(numbers[dest[0].idnum])
            result.append((" ".join(page.extract_text().split()), links))
        return result

    def test_phone_catalog_opens_books_through_files_and_lists_what_search_needs(self):
        name = "water #1 (2026).pdf"
        water = self.asset("water", "Water & sanitation", "CRITICAL/WATER/" + name, tags=["boil water"],
                           description="How to make water safe to drink. Original PDF retained without alteration.")
        aid = self.asset("hesperian_en_wtnd_2025_10", "Where There Is No Doctor — 10 First aid", "BOOKS/WTND/10.pdf")
        chapters = [self.asset(f"hesperian_en_wtnd_2025_{i}", f"Where There Is No Doctor — {i} Care", f"BOOKS/WTND/{i}.pdf")
                    for i in (11, 12)]
        note = self.asset("note", "Water notes", "BOOKS/water.txt", format="txt")
        assets = [water, aid, *chapters, note]
        inventory = {"assets": assets, "unresolved": [{"id": "missing", "title": "Absent guide"}],
                     "navigation": {"reader_topics": {"water": [["safe-water", "Safe water"]]}},
                     "phone_volumes": [{"file": "wikimed-emergencies.pdf", "title": "Emergencies", "bytes": 9,
                                        "articles": [{"title": "Bleeding"}, {"title": "Choking"}]}]}
        root = "shareddocuments:///private/var/mobile/Library/LiveFiles/com.apple.filesystems.userfsd/"
        volume = "D8CE3C96-2155-39B9-ACA4-EA1CF1876615"
        aid_link = root + volume + "/LIBRARY/BOOKS/WTND/10.pdf?open"
        water_link = root + volume + "/LIBRARY/CRITICAL/WATER/water%20%231%20%282026%29.pdf?open"
        emergencies = root + volume + "/LIBRARY/CRITICAL/MEDICAL/WIKIMED-PHONE/wikimed-emergencies.pdf?open"

        # Without the drive's volume UUID, every title switches to Files and the filename stands alone to be copied.
        plain = self.phone_pages(generate_navigation(self.target, assets, inventory, {}, write=False))
        text = "\n".join(page for page, _ in plain)
        self.assertEqual({link for _, links in plain for link in links if isinstance(link, str)}, {"shareddocuments://"})
        self.assertIn("Blue titles switch to Files", plain[0][0])
        self.assertIn(name + " LIBRARY › CRITICAL › WATER", text)
        self.assertIn("water.txt", text)
        self.assertNotIn("Absent guide", text)

        linked = self.phone_pages(generate_navigation(self.target, assets, inventory, {}, write=False, drive=volume))
        home, links = linked[0]

        def first(start):
            """The number of the first page whose text starts this way."""
            return next(number for number, (page, _) in enumerate(linked, 1) if page.startswith(start))

        # Home: the search card, each urgent task with a guide on the drive, then the ways into the library.
        self.assertIn("Blue titles open the book", home)
        self.assertIn("Stop severe bleeding 10 First aid · page 6", home)
        self.assertIn("Make drinking water safer Water & sanitation", home)
        self.assertIn("Find or build shelter No guide on this drive", home)
        help_page = len(linked)
        self.assertEqual(links[0], help_page)
        self.assertEqual(links[1:4], [aid_link, aid_link, water_link])
        self.assertEqual(links[4:], [first("‹ Home Browse by subject"), first("‹ Home Topics A to Z"),
                                     first("‹ Home Medical articles A to Z"), help_page])
        self.assertEqual(first("‹ Home Browse by subject"), 2)
        # Urgent help: the page to turn to, the words a person might type, and the WikiMed article when it is here.
        urgent, urgent_links = linked[first("‹ Home Urgent help") - 1]
        self.assertIn("Search words: bleeding, bleed, blood", urgent)
        self.assertIn("Go to page 6", urgent)
        self.assertIn("WikiMed: Bleeding In the WikiMed PDF “Emergencies”", urgent)
        self.assertIn(emergencies, urgent_links)
        # A topic leads straight to its book.
        topics, topic_links = linked[first("‹ Home Topics A to Z") - 1]
        self.assertIn("Safe water Water & sanitation", topics)
        self.assertIn(water_link, topic_links)
        # A subject page says what each book covers; other files show their folder in Files.
        rows = "\n".join(page for page, _ in linked)
        self.assertIn("How to make water safe to drink. Covers: boil water · Safe water LIBRARY › CRITICAL › WATER › " + name, rows)
        self.assertNotIn("retained", rows)
        self.assertIn(root + volume + "/LIBRARY/BOOKS", [link for _, links in linked for link in links])
        # A book in three or more files gets its own page of chapters, each opening its file.
        book = first("‹ Health Where There Is No Doctor")
        row_page = next(number for number, (page, _) in enumerate(linked, 1)
                        if "Where There Is No Doctor › Book, 3 chapters" in page)
        self.assertIn(book, linked[row_page - 1][1])
        self.assertEqual(linked[book - 1][1], [row_page, aid_link, root + volume + "/LIBRARY/BOOKS/WTND/11.pdf?open",
                                               root + volume + "/LIBRARY/BOOKS/WTND/12.pdf?open"])
        # Every WikiMed article is listed, so a search for a condition finds the volume that holds it.
        articles = linked[first("‹ Home Medical articles A to Z") - 1][0]
        self.assertIn("B Bleeding Emergencies C Choking Emergencies", articles)
        self.assertIn("Open a book Tap a blue title, then tap Open.", linked[-1][0])

        empty = self.phone_pages(self.generate([]))
        self.assertEqual(len(empty), 2)
        self.assertIn("There are no reading files on this drive.", empty[0][0])
        self.assertEqual(empty[0][1], [2, 2])

    def test_icon_paths_and_sizes_are_drawn_from_whole_numbers(self):
        from owl.phone_catalog import _size, svg_segments
        # A full circle drawn as two half-turn arcs ends where it began, in four quarter curves.
        circle = svg_segments("M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z")
        self.assertEqual([segment[0] for segment in circle], ["M", "C", "C", "C", "C", "Z"])
        self.assertEqual([round(value, 6) for value in circle[2][-2:]], [12, 21])
        self.assertEqual([round(value, 6) for value in circle[4][-2:]], [12, 3])
        self.assertEqual(svg_segments("M4 20l8-8h2V4"), [("M", 4.0, 20.0), ("L", 12.0, 12.0), ("L", 14.0, 12.0), ("L", 14.0, 4.0)])
        self.assertEqual([_size(value) for value in (999, 1_000, 5_603_996, 9_950_000, 14_400_000, 2_215_520_569)],
                         ["", "1.0 KB", "5.6 MB", "10 MB", "14 MB", "2.2 GB"])

    def test_reader_summary_keeps_only_what_a_book_covers(self):
        from owl.navigation import reader_summary
        self.assertEqual(reader_summary("First aid, rescue and preparedness. Original publication retained without alteration."),
                         "First aid, rescue and preparedness.")
        self.assertEqual(reader_summary("Complete finished PDF, 512 pages. Downloaded, parsed and SHA-256 checked; no conversion."), "")
        self.assertEqual(reader_summary(None), "")

    @unittest.skipIf(os.name == "nt", "POSIX mount layout")
    def test_drive_path_uses_the_volume_uuid_that_macos_reports(self):
        import plistlib
        import subprocess
        from unittest.mock import patch
        from owl.phone_catalog import drive_path
        volume = "D8CE3C96-2155-39B9-ACA4-EA1CF1876615"
        mounts = {"/", "/Volumes/KINGSTON", "/media/ana/OWL DRIVE"}
        calls = []

        def diskutil(command, **options):
            calls.append(command)
            if command[-1] != "/Volumes/KINGSTON":
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0, plistlib.dumps({"VolumeUUID": volume}), b"")

        with patch("owl.phone_catalog.os.path.ismount", side_effect=lambda path: Path(path).as_posix() in mounts), \
                patch.object(Path, "resolve", lambda self: self), \
                patch("owl.phone_catalog.subprocess.run", side_effect=diskutil):
            with patch("owl.phone_catalog.sys.platform", "darwin"):
                self.assertEqual(drive_path("/Volumes/KINGSTON"), volume)
                self.assertEqual(drive_path("/Volumes/KINGSTON/My library"), volume + "/My library")
                self.assertIsNone(drive_path("/Users/ana/Downloads/library"))
                mounts.add("/Volumes/BROKEN")
                self.assertIsNone(drive_path("/Volumes/BROKEN/library"))
            # Linux and Windows do not report the UUID an iPhone uses.
            with patch("owl.phone_catalog.sys.platform", "linux"):
                self.assertIsNone(drive_path("/media/ana/OWL DRIVE"))
        self.assertEqual(calls, [["diskutil", "info", "-plist", "/Volumes/KINGSTON"]] * 2 +
                         [["diskutil", "info", "-plist", "/Volumes/BROKEN"]])

    def test_phone_drive_prefers_the_live_uuid_and_keeps_a_saved_one_for_the_same_folder(self):
        from unittest.mock import patch
        from owl.phone_catalog import phone_drive
        volume = "D8CE3C96-2155-39B9-ACA4-EA1CF1876615"
        saved = {"path": volume, "folder": "KINGSTON"}
        with patch("owl.phone_catalog.drive_path", return_value="0D0C0B0A-0000-3000-8000-000000000000"):
            self.assertEqual(phone_drive("/Volumes/KINGSTON", saved),
                             {"path": "0D0C0B0A-0000-3000-8000-000000000000", "folder": "KINGSTON"})
        with patch("owl.phone_catalog.drive_path", return_value=None), \
                patch.object(Path, "resolve", lambda self: self):
            self.assertEqual(phone_drive("/media/ana/KINGSTON", saved), saved)
            self.assertEqual(phone_drive("/", {"path": volume + "/My library", "folder": "My library"}),
                             {"path": volume + "/My library", "folder": "My library"})
            self.assertIsNone(phone_drive("/media/ana/OTHER", saved))
            self.assertIsNone(phone_drive("/media/ana/KINGSTON", {"path": "KINGSTON", "folder": "KINGSTON"}))
            self.assertIsNone(phone_drive("/media/ana/KINGSTON", {"path": volume + "/../x", "folder": "KINGSTON"}))
            self.assertIsNone(phone_drive("/media/ana/KINGSTON", None))

    def test_emergency_uses_article_route_or_reports_the_missing_file(self):
        wiki = self.asset('wikimed_en', 'Medical encyclopedia', 'ZIM/medicine.zim', format='zim')
        pages = self.generate([wiki])
        home = reader_data(script(pages, 'home.js'), 'home')
        task = next(task for task in home['tasks'] if task['task'] == 'Care for burns')
        self.assertEqual(task['articles'], ['Burn'])
        self.assertEqual(task['format'], 'zim')
        self.assertIn('Look up Burn in Kiwix', pages['START_HERE.html'])
        content = ''.join(StaticHTML(pages['START_HERE.html']).text)
        self.assertIn('Care for burnsMedical encyclopedia · Look up Burn in KiwixLIBRARY › ZIMmedicine.zim', content)
        for device in ('iPhone', 'Android phone'):
            self.assertIn(device, content)
        # Computers read encyclopedias in the page; the static page sends them there.
        self.assertNotIn('Windows PC', content)
        self.assertIn('On a computer, open START_HERE.html in a web browser.', content)
        self.assertEqual(len(home['tasks']), len(layout()['tasks']))
        self.assertTrue(all('path' not in task for task in
                            reader_data(script(self.generate([]), 'home.js'), 'home')['tasks']))

    def test_urgent_row_names_the_page_and_categories_expand_in_place(self):
        aid = self.asset('hesperian_en_wtnd_2025_10', 'First aid chapter', 'CRITICAL/MEDICAL/aid.pdf')
        start = self.generate([aid])['START_HERE.html']
        self.assertIn('<a href="LIBRARY/CRITICAL/MEDICAL/aid.pdf#page=6">Stop severe bleeding</a></b>'
                      '<small>First aid chapter · page 6</small>', start)
        self.assertIn('<a href="LIBRARY/CRITICAL/MEDICAL/aid.pdf">Care for burns</a></b><small>First aid chapter</small>', start)
        self.assertIn('<b>Make drinking water safer</b><small>No guide on this drive.</small></div>', start)
        self.assertRegex(start, r'<details class="shelf"[^>]*><summary>.*?Health<small>1 guide</small>')
        self.assertNotRegex(start, r'href="#(?:c-|top)')

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
            self.assertEqual({key: output_bytes(value) for key, value in expected.items()},
                             {key: managed_path(self.target, key).read_bytes() for key in written})
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
