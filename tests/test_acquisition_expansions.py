"""Expansion metadata must never masquerade as measured, accepted content."""
import csv
import io
import unittest

from owl.acquisition.expansions import gutenberg_candidates, ocw_candidates, work_key
from owl.acquisition.model import AcquisitionError


class ExpansionTests(unittest.TestCase):
    def catalog(self, rows):
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(['Text#', 'Type', 'Issued', 'Title', 'Language', 'Authors', 'Subjects'])
        writer.writerows(rows)
        return out.getvalue().encode()

    def test_book_selection_is_deterministic_balanced_and_excludes_existing_works(self):
        rows = [[str(i), 'Text', '2020-01-01', title, lang, 'Writer', subject] for i, title, lang, subject in [
            (1,'Existing','en','Fiction'), (2,'Duplicate','en','Fiction'), (3,'History','en','History'),
            (4,'Foreign','es','Fiction'), (5,'New novel','en','Fiction'), (6,'Duplicate','en','Fiction')]]
        kwargs = dict(existing_ids=[1], existing_work_keys=[work_key('Duplicate','Writer')], limit=2)
        result = gutenberg_candidates(self.catalog(rows), **kwargs)
        self.assertEqual(result, gutenberg_candidates(self.catalog(list(reversed(rows))), **kwargs))
        self.assertEqual([r['book_id'] for r in result], [5,3])
        self.assertTrue(all(not r['content_ready'] and not r['source_files'] for r in result))

    def test_duplicate_catalog_ids_and_malformed_metadata_fail(self):
        row = ['1','Text','2020','Book','en','Writer','Fiction']
        with self.assertRaises(AcquisitionError):
            gutenberg_candidates(self.catalog([row,row]))
        with self.assertRaises(AcquisitionError):
            gutenberg_candidates(b'Title\nA book\n')

    def test_ocw_preserves_media_but_does_not_claim_complete_page_inventory(self):
        course = {'id':'sample','rank':1,'download_url':'https://ocw.mit.edu/courses/sample/download/'}
        html = b'<a href="/courses/sample/sample.zip">Download course</a><a href="https://archive.org/download/a/a.mp4">Video</a><a href="/courses/sample/c.vtt">Caption</a>'
        result = ocw_candidates(course, html)
        self.assertEqual({r['role'] for r in result['source_files']}, {'course_package','media','caption'})
        self.assertTrue(all(r['size_bytes'] is None and r['sha256'] is None for r in result['source_files']))
        self.assertFalse(result['content_ready'])
        self.assertTrue(any('paginate' in b for b in result['blockers']))
        with self.assertRaises(AcquisitionError):
            ocw_candidates(course, b'<a href="https://unreviewed.example/a.zip">Download</a>')
