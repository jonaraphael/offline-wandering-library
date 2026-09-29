import hashlib
import importlib.util
import json
import random
from pathlib import Path
import tempfile
import unittest

import pymupdf

from owl.safety import SafetyError

spec = importlib.util.spec_from_file_location('survivor_scan', Path(__file__).parents[1] / 'scripts/inspect_survivor_capture.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class SurvivorScanReviewTests(unittest.TestCase):
    def fixture(self, path):
        with pymupdf.open() as pdf:
            for i in range(9):
                page = pdf.new_page()
                page.insert_text((72, 72), ('Contents: Smithing, Tools, Index' if i == 1 else f'Practical tools page {i + 1}') + '\n' + 'Instructions and figures. ' * 8)
            pdf.save(path)
        return {'id': 'book', 'size_bytes': path.stat().st_size}, {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_whole_page_checks_and_deterministic_sparse_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'book.pdf'; source, receipt = self.fixture(path)
            output = {}; emit = lambda name, data: output.update({name: data})
            first = review.inspect_pdf(path, source, receipt, emit)
            second = review.inspect_pdf(path, source, receipt, emit)
            self.assertEqual(first, second)
            self.assertEqual(len(first['pages']), 9)
            self.assertTrue(all(row['rendered'] for row in first['pages']))
            self.assertIn(2, first['table_of_contents_candidate_pages'])
            self.assertLess(len(output), 9)
            self.assertFalse(first['sampling']['completeness_proven'])
            self.assertTrue(first['required_review'])
            path.write_bytes(path.read_bytes() + b'changed')
            with self.assertRaisesRegex(SafetyError, 'changed'):
                review.inspect_pdf(path, source, receipt, emit)

    def test_changed_cached_sample_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'inspection.json'; image = path.parent / 'sample.png'; image.write_bytes(b'original')
            binding = {'source_sha256': 'a' * 64}
            path.write_text(json.dumps({'binding': binding, 'content_ready': False,
                'renders': [{'path': 'sample.png', 'size_bytes': 8, 'sha256': hashlib.sha256(b'original').hexdigest()}]}))
            self.assertIsNotNone(review.cached(path, binding))
            image.write_bytes(b'different')
            with self.assertRaisesRegex(SafetyError, 'render changed'): review.cached(path, binding)

    def test_dense_scan_sample_keeps_resolution_within_existing_byte_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'noisy.pdf'
            with pymupdf.open() as pdf:
                page = pdf.new_page(width=1200, height=1200)
                pixels = pymupdf.Pixmap(pymupdf.csRGB,1200,1200,random.Random(17).randbytes(1200*1200*3),False)
                page.insert_image(page.rect,pixmap=pixels);pdf.save(path)
            source={'id':'scan','size_bytes':path.stat().st_size}
            receipt={'sha256':hashlib.sha256(path.read_bytes()).hexdigest()};output={}
            result=review.inspect_pdf(path,source,receipt,lambda name,data:output.update({name:data}))
            self.assertEqual(list(output),['page-1.jpg'])
            self.assertLess(len(output['page-1.jpg']),review.MAX_RECORD)
            pixmap=pymupdf.Pixmap(output['page-1.jpg'])
            self.assertEqual((pixmap.width,pixmap.height),(1200,1200))
            self.assertTrue(result['flags'])

    def test_write_budget_and_ownership_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); owner = {'output_budget_bytes': 100, 'reserve_bytes': 1}
            (root / 'owner.json').write_text(json.dumps(owner))
            with self.assertRaisesRegex(SafetyError, 'bound'): review.write(root, root / 'too-big', b'x' * 100, owner)
            with self.assertRaisesRegex(SafetyError, 'owner'): review.write(root, root / 'small', b'x', {**owner, 'reserve_bytes': 2})
