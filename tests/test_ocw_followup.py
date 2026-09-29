import importlib.util
from pathlib import Path
import unittest

from owl.acquisition.capture import normalize_manifest
from owl.safety import SafetyError


spec = importlib.util.spec_from_file_location("ocw_followup", Path(__file__).resolve().parents[1] / "scripts/prepare_ocw_followup.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FollowupTests(unittest.TestCase):
    def manifest(self):
        source = {"id": "media", "source_url": "https://archive.org/download/course/lecture.mp4",
            "resource_ids": ["complete-courses-expansion"], "version": "1", "size_bytes": 1234,
            "sha256": None, "publisher_checksums": {"md5": "a" * 32},
            "metadata_evidence": [{"url": "https://archive.org/metadata/course", "sha256": "b" * 64}]}
        return normalize_manifest({"schema_version": 1, "kind": "acquisition", "id": "media-course", "profile": "full-1tb",
            "sources": [source], "budget": {"download_bytes": 1234, "expanded_bytes": 0, "preview_bytes": 0,
                "scratch_bytes": 0, "cache_bytes": 0}})

    def test_shared_media_is_referenced_and_never_double_counted(self):
        manifest = self.manifest(); source = manifest['sources'][0]
        proposal, reused = module.deduplicate_manifest(manifest, {source['source_url']: source})
        self.assertIsNone(proposal)
        self.assertEqual(reused[0]['id'], source['id'])
        proposal, reused = module.deduplicate_manifest(manifest, {})
        self.assertEqual(proposal['budget']['download_bytes'], 1234)
        self.assertEqual(reused, [])

    def test_changed_shared_media_is_not_silently_reused(self):
        manifest = self.manifest(); source = manifest['sources'][0]
        for change in ({'size_bytes': 1235}, {'publisher_checksums': {'md5': 'c' * 32}}):
            with self.assertRaises(SafetyError):
                module.deduplicate_manifest(manifest, {source['source_url']: {**source, **change}})

    def test_aggregate_metadata_is_bounded(self):
        class Fetcher:
            def fetch(self, url, *, kind, max_bytes):
                return b'x' * min(4, max_bytes)
        budget = module.BudgetMetadata(Fetcher(), lambda additional: None, maximum=5)
        budget.fetch('one', kind='json'); budget.fetch('two', kind='json')
        self.assertEqual(budget.used, 5)
        with self.assertRaisesRegex(SafetyError, 'allowance'):
            budget.fetch('three', kind='json')


if __name__ == '__main__':
    unittest.main()
