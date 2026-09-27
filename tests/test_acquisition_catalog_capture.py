from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

SPEC=importlib.util.spec_from_file_location('prepare_catalog_capture',
    Path(__file__).resolve().parents[1]/'scripts/prepare_catalog_capture.py')
module=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class CatalogCaptureTests(unittest.TestCase):
    def setUp(self):
        self.asset={'id':'book','source_url':'https://example.org/book.zim',
            'status':'resolved','sha256':'a'*64,'size_bytes':100,'version':'2026-01'}
        self.resources={'books':{'asset_ids':['book']}}

    def freeze(self, asset=None, selected=('book',), resources=('books',), ids=('book',)):
        return module.freeze('books-v1','full-1tb',[asset or self.asset],
            self.resources,set(selected),list(ids),set(resources))

    def test_deterministic_pins_and_separate_budget(self):
        result=self.freeze()
        self.assertEqual(result,self.freeze())
        self.assertEqual(result['sources'][0]['sha256'],'a'*64)
        self.assertEqual(result['budget']['download_bytes'],100)
        self.assertFalse(result['content_ready'])
        self.assertGreater(result['storage_peak_bytes'],100)

    def test_rejects_unpinned_or_generated_sources(self):
        for change in ({'sha256':None},{'status':'pending'},
                       {'generation':{'recipe_id':'generated'}},
                       {'archive_member':{'source_asset_id':'archive'}}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.freeze({**self.asset,**change})

    def test_rejects_duplicates_or_out_of_scope_sources(self):
        with self.assertRaises(ValueError): self.freeze(ids=('book','book'))
        with self.assertRaises(ValueError): self.freeze(selected=())
        with self.assertRaises(ValueError): self.freeze(resources=('other',))


if __name__=='__main__': unittest.main()
