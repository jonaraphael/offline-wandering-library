"""Trial status respects filtered identities and cannot create ownership."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from owl.acquisition.capture import _digest, _json, load_manifest, normalize_manifest


class TrialStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        spec = importlib.util.spec_from_file_location("trial_status", Path(__file__).resolve().parents[1] / "scripts/acquisition_trial_status.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.ROOT = self.root
        self.staging = self.root / "staging"
        self.staging.mkdir()
        source = {"id": "sheet", "source_url": "https://example.org/sheet.pdf", "version": "2024", "size_bytes": 32,
            "resource_ids": ["regional-maps"], "sha256": None,
            "metadata_evidence": [{"url": "https://example.org/meta", "sha256": "a" * 64}]}
        manifest = normalize_manifest({"schema_version": 1, "kind": "acquisition", "id": "map", "profile": "full-1tb",
            "sources": [source], "budget": {"download_bytes": 32, "expanded_bytes": 0, "preview_bytes": 0, "scratch_bytes": 0, "cache_bytes": 0}})
        (self.root / "manifest.json").write_bytes(_json(manifest))
        self.filtered = load_manifest(self.root / "manifest.json", profile="full-1tb", resource_ids=["regional-maps"])
        capture = self.staging / "maps"
        capture.mkdir()
        self.owner = {"owner": "owl-acquisition-capture", "manifest_sha256": _digest(self.filtered)}
        (capture / "owner.json").write_bytes(_json(self.owner))
        (capture / "manifest.json").write_bytes(_json(self.filtered))
        self.batch = {"id": "maps", "staging": "maps", "manifest": "manifest.json", "profile": "full-1tb", "resource_ids": ["regional-maps"]}

    def report(self, batches):
        return self.module.report(self.staging, {"schema_version": 1, "shared_reserve_bytes": 0, "batches": batches})

    def test_filtered_manifest_matches_captured_owner(self):
        result = self.report([self.batch])
        self.assertNotEqual(result["batches"][0]["state"], "exception")
        self.assertTrue(result["combined_declared_phases_fit"])
        unfiltered = {key: value for key, value in self.batch.items() if key not in {"profile", "resource_ids"}}
        self.assertEqual(self.report([unfiltered])["batches"][0]["state"], "exception")

    def test_unowned_existing_directory_is_never_adopted(self):
        marker = self.staging / "maps/owner.json"
        marker.unlink()
        self.assertEqual(self.report([self.batch])["batches"][0]["state"], "exception")
        self.assertFalse(marker.exists())

    def test_absent_future_job_is_planned_with_its_full_peak_reserved(self):
        batch = {**self.batch, 'staging': 'future-maps', 'job': 'future-job'}
        result = self.report([batch])
        row = result['batches'][0]
        self.assertEqual(row['state'], 'planned')
        self.assertEqual(row['retained_bytes'], 0)
        self.assertEqual(row['remaining_peak_bytes'], row['storage_peak_bytes'])
        self.assertEqual(result['reserved_remaining_bytes'], row['storage_peak_bytes'])
        self.assertTrue(result['combined_declared_phases_fit'])
        self.assertFalse((self.root / 'future-job').exists())

    def test_registry_cannot_double_count_a_staging_directory(self):
        with self.assertRaisesRegex(ValueError, 'repeats'):
            self.report([self.batch, {**self.batch, 'id': 'second-name'}])

    def test_future_preview_reservation_is_bound_to_frozen_source_budget(self):
        budget={**self.filtered['budget'],'preview_bytes':2000000}
        batch={**self.batch,'staging':'future-maps','planned_phase_budget':budget}
        result=self.report([batch])
        self.assertTrue(result['combined_declared_phases_fit'])
        self.assertEqual(result['batches'][0]['storage_peak_bytes'],
                         sum(budget.values())+self.filtered['metadata_allowance_bytes'])
        self.assertFalse((self.staging/'future-maps').exists())
        for invalid in ({**budget,'download_bytes':0},{**budget,'preview_bytes':True},
                        {'preview_bytes':2000000}):
            with self.subTest(invalid=invalid):
                self.assertFalse(self.report([{**batch,'planned_phase_budget':invalid}])['combined_declared_phases_fit'])
        self.assertFalse(self.report([{'id':'unbound','staging':'unbound','review_peak_bytes':100,
                                       'planned_phase_budget':budget}])['combined_declared_phases_fit'])

    def test_expanded_registry_keeps_a_finite_batch_bound(self):
        batches = [{'id': 'phase-'+str(i), 'staging': 'phase-'+str(i), 'review_peak_bytes': 1000}
                   for i in range(64)]
        self.assertEqual(self.report(batches)['reserved_remaining_bytes'], 64000)
        with self.assertRaisesRegex(ValueError, '1–64'):
            self.report(batches + [{'id': 'overflow', 'staging': 'overflow', 'review_peak_bytes': 1}])

    def test_full_peak_preflight_gives_no_retained_credit(self):
        from unittest.mock import patch
        registry={'schema_version':1,'shared_reserve_bytes':17,'batches':[self.batch],
                  'space_accounting':'reserve-full-peaks'}
        with patch.object(self.module,'_usage',side_effect=AssertionError('No traversal expected')):
            result=self.module.report(self.staging,registry)
        row=result['batches'][0]
        self.assertIsNone(row['retained_bytes'])
        self.assertFalse(result['retained_usage_measured'])
        self.assertEqual(result['reserved_remaining_bytes'],row['storage_peak_bytes']+17)
        # Avoiding the traversal must never avoid identity validation.
        (self.staging/'maps/owner.json').unlink()
        self.assertFalse(self.module.report(self.staging,registry)['combined_declared_phases_fit'])

    def test_existing_ownerless_future_job_is_still_an_error(self):
        (self.root / 'future-job').mkdir()
        result = self.report([{**self.batch, 'staging': 'future-maps', 'job': 'future-job'}])
        self.assertEqual(result['batches'][0]['state'], 'exception')
        self.assertFalse(result['combined_declared_phases_fit'])

    def test_review_budget_source_binding_and_pending_report_are_verified(self):
        review = self.staging / "review"
        review.mkdir()
        owner = {"schema_version": 1, "owner": "owl-map-pdf-review", "manifest_sha256": self.owner["manifest_sha256"],
            "output_budget_bytes": 1000000, "reserve_bytes": 0}
        (review / "owner.json").write_bytes(_json(owner))
        (review / "report.json").write_bytes(_json({"manifest_sha256": owner["manifest_sha256"], "content_ready": False,
            "status": "awaiting_review", "inspected_sources": 1, "requested_sources": 1, "failed_check_counts": {},
            "rows": [{"source_id": "sheet", "status": "inspected_awaiting_review"}]}))
        batch = {"id": "map-review", "staging": "review", "review_peak_bytes": 1000000,
            "review_owner": "owl-map-pdf-review", "source_staging": "maps"}
        row = self.report([batch])["batches"][0]
        self.assertEqual(row["inspected_sources"], 1)
        self.assertEqual(row["inspection_state"], "awaiting_review")
        for change in ({"output_budget_bytes": 900000}, {"manifest_sha256": "b" * 64}):
            (review / "owner.json").write_bytes(_json({**owner, **change}))
            self.assertEqual(self.report([batch])["batches"][0]["state"], "exception")


if __name__ == "__main__":
    unittest.main()
