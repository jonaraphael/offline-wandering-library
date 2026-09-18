"""Publisher structure import uses verified tiny files and never downloads."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject
import yaml

from owl.atlas_import import SectionImportError, import_sections, main
from owl.safety import SafetyError

ROOT = Path(__file__).resolve().parents[1]


class SectionImporterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name).resolve()

    def source(self, name, data, **metadata):
        path = self.target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
        return path, {'id': 'source_book', 'destination': name, 'format': path.suffix[1:],
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'size_bytes': path.stat().st_size, **metadata}

    def pdf(self, writer):
        stream = io.BytesIO()
        writer.write(stream)
        return self.source('BOOKS/source.pdf', stream.getvalue())

    def writer(self, count=4):
        writer = PdfWriter()
        for _ in range(count):
            writer.add_blank_page(width=612, height=792)
        return writer

    def test_pdf_preserves_publisher_hierarchy_and_physical_pages(self):
        writer = self.writer()
        parent = writer.add_outline_item('Part One', 0)
        child = writer.add_outline_item('Water safety', 2, parent=parent)
        writer.add_outline_item('Boiling', 3, parent=child)
        writer.add_outline_item('Part Two', 3)
        path, asset = self.pdf(writer)
        section_map, report = import_sections(path, asset)
        sections = section_map['sections']
        self.assertEqual([s['locator']['page'] for s in sections], [1, 3, 4, 4])
        self.assertEqual(sections[1]['parent'], sections[0]['id'])
        self.assertEqual(sections[2]['parent'], sections[1]['id'])
        self.assertNotIn('parent', sections[3])
        self.assertEqual(sections[1]['title'], 'Water safety')
        self.assertTrue(all(s['provenance'] == 'publisher-outline' for s in sections))
        self.assertEqual(report['physical_pages'], 4)
        self.assertEqual(report['status'], 'draft')
        self.assertFalse(report['fallback_required'])
        self.assertEqual(section_map['source_sha256'], asset['sha256'])
        self.assertEqual(import_sections(path, asset), (section_map, report))
        self.assertEqual(len(report['structure_sha256']), 64)

    def test_named_pdf_destination_is_verified_against_actual_page_tree(self):
        writer = self.writer()
        writer.add_named_destination('water', 2)
        reference = writer.add_outline_item('Named water chapter', 0)
        node = reference.get_object()
        del node['/A']
        node[NameObject('/Dest')] = TextStringObject('water')
        section_map, report = import_sections(*self.pdf(writer))
        self.assertEqual(section_map['sections'][0]['locator'], {'type': 'pdf-page', 'page': 3})
        self.assertEqual(report['status'], 'draft')

    def test_external_missing_and_nonpage_pdf_destinations_are_not_invented(self):
        writer = self.writer()
        external = writer.add_outline_item('External', 0).get_object()
        external[NameObject('/A')] = DictionaryObject({NameObject('/S'): NameObject('/URI'),
                                                      NameObject('/URI'): TextStringObject('https://example.invalid/')})
        missing = writer.add_outline_item('No destination', 0).get_object()
        del missing['/A']
        invalid = writer.add_outline_item('Invalid page', 0).get_object()
        invalid['/A'][NameObject('/D')] = ArrayObject([NumberObject(999999), NameObject('/Fit')])
        section_map, report = import_sections(*self.pdf(writer))
        self.assertEqual(section_map['sections'], [])
        self.assertEqual(report['status'], 'whole-document-fallback')
        self.assertTrue(any('External' in warning for warning in report['warnings']))
        self.assertTrue(any('physical page' in warning for warning in report['warnings']))

    def test_invalid_pdf_fit_does_not_silently_become_page_one(self):
        writer = self.writer()
        node = writer.add_outline_item('Invalid fit', 2).get_object()
        node['/A'][NameObject('/D')] = ArrayObject([writer.pages[2].indirect_reference, NameObject('/NotAFit')])
        section_map, report = import_sections(*self.pdf(writer))
        self.assertEqual(section_map['sections'], [])
        self.assertEqual(report['status'], 'whole-document-fallback')
        self.assertGreater(report['warning_count'], 0)

    def test_pdf_without_outline_and_corrupt_verified_pdf_fail_soft(self):
        for source in (self.pdf(self.writer()), self.source('broken.pdf', b'not a PDF file')):
            with self.subTest(path=source[0]):
                section_map, report = import_sections(*source)
                self.assertEqual(section_map['sections'], [])
                self.assertTrue(report['review_required'])
                self.assertTrue(report['fallback_required'])

    def test_encrypted_pdf_without_password_returns_only_fallback(self):
        writer = self.writer()
        writer.add_outline_item('Encrypted chapter', 2)
        writer.encrypt('not-available-offline')
        section_map, report = import_sections(*self.pdf(writer))
        self.assertEqual(section_map['sections'], [])
        self.assertTrue(any('Encrypted' in warning for warning in report['warnings']))

    def test_html_preserves_hierarchy_anchors_unicode_and_title_text(self):
        source = self.source('BOOKS/guide.html', '''
        <h1 id="guide">Publisher &amp; Guide</h1>
        <h2 id="water">Water<br>Safety</h2>
        <h3><span id="café:boil">Boiling <em>water</em></span></h3>
        <h2 id="food">Food safety</h2>
        <script><h2 id="fake">Fake heading</h2></script>
        ''')
        section_map, report = import_sections(*source)
        sections = section_map['sections']
        self.assertEqual([s['title'] for s in sections],
                         ['Publisher & Guide', 'Water Safety', 'Boiling water', 'Food safety'])
        self.assertEqual(sections[1]['parent'], 'heading-0001')
        self.assertEqual(sections[2]['parent'], 'heading-0002')
        self.assertEqual(sections[3]['parent'], 'heading-0001')
        self.assertEqual(sections[2]['locator'], {'type': 'html-anchor', 'id': 'café:boil'})
        self.assertTrue(all(s['provenance'] == 'publisher-heading' for s in sections))
        self.assertEqual(report['status'], 'draft')

    def test_duplicate_ids_are_checked_across_the_entire_streamed_html(self):
        markup = '<h1 id="duplicate">Unsafe anchor</h1>' + ('padding ' * 30_000)
        markup += '<div id="duplicate">Later duplicate</div><h1 id="unique">Good heading</h1>'
        section_map, report = import_sections(*self.source('guide.html', markup))
        self.assertEqual([s['id'] for s in section_map['sections']], ['heading-0002'])
        self.assertEqual(report['status'], 'partial-draft')
        self.assertTrue(any('duplicated' in warning for warning in report['warnings']))

    def test_duplicate_id_on_a_hidden_element_is_not_accepted(self):
        section_map, report = import_sections(*self.source('guide.html',
            '<h1 id="same">Visible</h1><script id="same">nothing</script>'))
        self.assertEqual(section_map['sections'], [])
        self.assertTrue(report['fallback_required'])

    def test_missing_ambiguous_invalid_and_overlong_html_anchors_are_omitted(self):
        cases = ['<h1>No anchor</h1>', '<h1 id="has space">Whitespace</h1>',
                 '<h1><a id="one"></a><a id="two"></a>Ambiguous</h1>',
                 '<h1 id="one" id="two">Malformed</h1>',
                 '<h1 id="' + 'x' * 1025 + '">Too long</h1>']
        for markup in cases:
            with self.subTest(markup=markup[:70]):
                section_map, report = import_sections(*self.source('guide.html', markup))
                self.assertEqual(section_map['sections'], [])
                self.assertEqual(report['status'], 'whole-document-fallback')

    def test_unlocated_parent_is_an_explicit_hierarchy_review_warning(self):
        section_map, report = import_sections(*self.source('guide.html',
            '<h1>Unlocated book title</h1><h2 id="chapter">Located chapter</h2>'))
        self.assertEqual([s['id'] for s in section_map['sections']], ['heading-0002'])
        self.assertNotIn('parent', section_map['sections'][0])
        self.assertTrue(any('hierarchy review' in warning for warning in report['warnings']))

    def test_warning_output_is_bounded_and_titles_are_not_silently_truncated(self):
        markup = ''.join('<h1>No anchor</h1>' for _ in range(40))
        markup += '<h1 id="long">' + 'x' * 501 + '</h1>'
        section_map, report = import_sections(*self.source('guide.html', markup))
        self.assertEqual(section_map['sections'], [])
        self.assertEqual(len(report['warnings']), 20)
        self.assertGreater(report['warning_count'], 40)

    def test_long_unterminated_html_never_invents_sections(self):
        # Python HTMLParser versions differ in when malformed tokens become
        # text; neither interpretation supplies a verifiable publisher heading.
        markup = '<div title="' + 'x' * (1024 * 1024 + 100)
        section_map, report = import_sections(*self.source('guide.html', markup))
        self.assertEqual(section_map['sections'], [])
        self.assertEqual(report['status'], 'whole-document-fallback')

    def test_explicit_html_encoding_is_respected(self):
        source = self.source('guide.html', '<h1 id="water">Café</h1>'.encode('utf-16'), text_encoding='utf-16')
        section_map, report = import_sections(*source)
        self.assertEqual(section_map['sections'][0]['title'], 'Café')
        self.assertEqual(report['status'], 'draft')

    def test_bad_or_missing_source_hash_and_wrong_size_are_hard_failures(self):
        path, asset = self.source('guide.html', '<h1 id="good">Good</h1>')
        for changes in ({'sha256': None}, {'sha256': '0' * 64}, {'size_bytes': 1}):
            with self.subTest(changes=changes), self.assertRaises(SectionImportError):
                import_sections(path, {**asset, **changes})

    def test_source_change_during_extraction_is_a_hard_failure(self):
        path, asset = self.source('guide.html', '<h1 id="good">Good</h1>')
        def changed(*args):
            path.write_bytes(b'changed while parsing')
            return []
        with patch('owl.atlas_import._html_structure', side_effect=changed):
            with self.assertRaisesRegex(SectionImportError, 'changed during'):
                import_sections(path, asset)

    def test_symlink_source_is_rejected(self):
        path, asset = self.source('guide.html', '<h1 id="good">Good</h1>')
        linked = self.target / 'link.html'
        linked.symlink_to(path)
        with self.assertRaises(SafetyError):
            import_sections(linked, asset)

    def test_cli_writes_only_draft_and_review_and_repeats_idempotently(self):
        path, asset = self.source('BOOKS/guide.html', '<h1 id="good">Good chapter</h1>')
        inventory = self.target / 'INVENTORY.json'
        inventory.write_text(json.dumps({'assets': [asset]}), encoding='utf-8')
        assignments = self.target / 'assignments.yaml'
        assignments.write_text('assignments: []\n', encoding='utf-8')
        output = self.target / 'drafts/guide.yaml'
        command = [sys.executable, str(ROOT / 'scripts/import_sections.py'), str(self.target),
                   '--asset', asset['id'], '--output', str(output)]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        section_map = yaml.safe_load(output.read_text(encoding='utf-8'))
        self.assertEqual(section_map['sections'][0]['locator']['id'], 'good')
        report_path = Path(str(output) + '.review.json')
        self.assertTrue(json.loads(report_path.read_text(encoding='utf-8'))['review_required'])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(command[2:]), 0)
        self.assertEqual(assignments.read_text(encoding='utf-8'), 'assignments: []\n')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), asset['sha256'])

    def test_cli_unknown_asset_traversal_and_existing_output_fail_without_mutation(self):
        _, asset = self.source('guide.html', '<h1 id="good">Good</h1>')
        inventory = self.target / 'INVENTORY.json'
        inventory.write_text(json.dumps({'assets': [asset]}), encoding='utf-8')
        output = self.target / 'assignments.yaml'
        output.write_text('existing assignments', encoding='utf-8')
        base = [str(self.target), '--asset', asset['id'], '--output', str(output)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(base), 1)
            self.assertEqual(main([str(self.target), '--asset', 'unknown', '--output', str(self.target/'new.yaml')]), 1)
        self.assertEqual(output.read_text(encoding='utf-8'), 'existing assignments')
        self.assertFalse(Path(str(output) + '.review.json').exists())
        inventory.write_text(json.dumps({'assets': [{**asset, 'destination': '../outside.html'}]}), encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(base), 1)
        self.assertFalse((self.target / 'new.yaml').exists())


if __name__ == '__main__':
    unittest.main()
