"""Tiny local fixtures exercise source-review acquisition without publisher bodies."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from owl.acquisition import capture as module
from owl.download import download, DownloadError
from owl.safety import SafetyError
from tests.process_fixtures import wait_for_windows_process_exit
from owl import jobs


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class ZimWriteLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.export = self.root / 'preview/LIBRARY'
        self.control = self.export / '.owl/exports/fixture/state.json'
        self.control.parent.mkdir(parents=True)

    def ledger(self, peak=1000, workspace=1000):
        return module._ZimWriteLedger(self.root, self.export, 'fixture', peak=peak,
                                     workspace=workspace, reserve=0)

    def test_atomic_overwrite_credit_requires_observed_replacement(self):
        self.control.write_bytes(b'a' * 80)
        ledger = self.ledger(peak=130)
        with self.assertRaisesRegex(SafetyError, 'total peak'):
            ledger(self.control, 60)  # Must reserve old + temporary new bytes.
        ledger = self.ledger(peak=150)
        ledger(self.control, 60)
        with self.assertRaisesRegex(SafetyError, 'did not complete'):
            ledger(self.control, 10)
        module.atomic_write(self.control, b'b' * 60)
        ledger.settle()
        self.assertEqual(ledger.used, 60)
        self.assertEqual(ledger.control, 60)

    def test_appended_parts_and_atomic_metadata_need_only_one_full_scan(self):
        with patch.object(module, '_usage', wraps=module._usage) as scan:
            ledger = self.ledger()
            part = self.export / '.owl/exports/fixture/parts/example.part'
            part.parent.mkdir()
            for _ in range(3):
                ledger(part, 7)
                with part.open('ab') as stream:
                    stream.write(b'1234567')
            final = self.export / 'example.html'
            part.replace(final)
            for size in (50, 60, 30):
                ledger(self.control, size)
                module.atomic_write(self.control, b'c' * size)
            ledger.settle()
            self.assertEqual(scan.call_count, 1)
            self.assertEqual(ledger.used, 51)
            self.assertEqual(ledger.control, 30)

    def test_unhooked_lock_growth_and_workspace_transient_are_charged(self):
        self.control.write_bytes(b'a' * 80)
        ledger = self.ledger(workspace=130)
        lock = self.export / '.owl/exports/fixture/export.lock'
        lock.write_bytes(b'1')
        with self.assertRaisesRegex(SafetyError, 'scratch allowance'):
            ledger(self.control, 50)
        self.assertEqual(ledger.used, 81)
        with patch.object(module.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 0})()):
            with self.assertRaisesRegex(SafetyError, 'free space'):
                ledger(self.control, 1)


class PreviewWriteLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.files = self.root / 'previews/manual/files'; self.files.mkdir(parents=True)
        self.candidate = self.root / 'work/page.html'; self.target = self.files / 'page.html'

    def ledger(self, peak=100, allowance=100, reserve=0):
        return module._PreviewWriteLedger(self.root, {self.candidate: self.target},
            peak=peak, allowance=allowance, reserve=reserve)

    def test_reuse_and_many_outputs_do_not_rescan_or_take_replacement_credit(self):
        with patch.object(module, '_usage', wraps=module._usage) as usage:
            ledger=self.ledger(); initial=usage.call_count
            for _ in range(4): ledger(self.candidate,b'complete')
            self.assertEqual(usage.call_count,initial)
            self.assertEqual(ledger.used,8); self.assertEqual(ledger.retained,8)
            ledger.reconcile(); self.assertEqual(usage.call_count,initial+1)
            with self.assertRaisesRegex(SafetyError,'deterministic rerender'): ledger(self.candidate,b'changed')
            self.assertEqual(self.target.read_bytes(),b'complete')

    def test_interrupted_atomic_write_needs_fresh_ledger_and_charges_leftover_bytes(self):
        ledger=self.ledger()
        def interrupted(target,data):
            (target.parent/'.owl-write-interrupted').write_bytes(data[:3])
            raise KeyboardInterrupt
        with patch.object(module,'atomic_write',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt): ledger(self.candidate,b'complete')
        with self.assertRaisesRegex(SafetyError,'reconstructed'): ledger(self.candidate,b'complete')
        fresh=self.ledger(); self.assertEqual(fresh.used,3)
        fresh(self.candidate,b'complete'); fresh.reconcile()
        self.assertEqual(fresh.used,11)

    def test_preview_total_free_space_and_collision_fail_before_write(self):
        for kwargs,pattern in [({'allowance':3},'preview_bytes'),({'peak':3},'total storage peak')]:
            ledger=self.ledger(**kwargs)
            with self.assertRaisesRegex(SafetyError,pattern): ledger(self.candidate,b'four')
            self.assertFalse(self.target.exists())
        ledger=self.ledger(reserve=10)
        with patch.object(module.shutil,'disk_usage',return_value=type('Disk',(),{'free':109})()):
            with self.assertRaisesRegex(SafetyError,'free space'): ledger(self.candidate,b'four')
        with self.assertRaisesRegex(SafetyError,'undeclared'): ledger(self.root/'other',b'four')
        self.target.write_bytes(b'')
        with self.assertRaisesRegex(SafetyError,'deterministic rerender'): ledger(self.candidate,b'four')
        self.target.unlink(); (self.files/'untracked').write_bytes(b'extra')
        with self.assertRaisesRegex(SafetyError,'outside'): ledger.reconcile()


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.body = self.root / "source.html"
        self.body.write_bytes(b'<html><body><article><h1>Complete guide</h1><p>Keep this complete.</p><table><tr><td>42</td></tr></table></article></body></html>')
        self.staging = self.root / "capture"
        self.document = {"schema_version": 1, "kind": "acquisition", "id": "fixture", "profile": "full-1tb",
            "sources": [{"id": "original", "resource_ids": ["reference"], "source_url": self.body.as_uri(),
                "version": "1", "size_bytes": self.body.stat().st_size,
                "metadata_evidence": [{"url": "https://publisher.test/metadata", "sha256": "a" * 64}],
                "publisher_checksums": {"md5": hashlib.md5(self.body.read_bytes()).hexdigest()},
                "fullasset_metadata": {"title": "Source", "format": "html", "destination": "references/source.html", "license": "CC0"}}],
            "budget": {"download_bytes": self.body.stat().st_size, "expanded_bytes": 0, "preview_bytes": 0,
                       "scratch_bytes": 0, "cache_bytes": 0}}
        self.manifest = write(self.root / "candidates.json", self.document)
        self.recipe = {"id": "fixture", "resource_id": "reference", "adapter": "html_snapshot", "version": "1",
            "source_asset_ids": ["original"], "output_asset_ids": ["guide"],
            "selection": {"outputs": [{"asset_id": "guide", "sections": [{"source_asset_id": "original", "tag": "article", "expected_count": 1}]}]},
            "review": {"status": "pending"}, "status": "pending"}
        self.recipe_path = write(self.root / "recipe.json", self.recipe)
        self.assets_path = write(self.root / "assets.json", {"assets": [{"id": "guide", "title": "Guide", "format": "html",
            "destination": "references/guide.html", "size_bytes": None, "sha256": None,
            "generation": {"recipe_id": "fixture"}}]})

    def capture(self, **kwargs):
        return module.capture(self.manifest, self.staging, allow_local=True, reserve_bytes=0, progress=lambda _: None, **kwargs)

    def preview(self, **kwargs):
        return module.preview(self.staging, self.recipe_path, self.assets_path, preview_bytes=10000, progress=lambda _: None, **kwargs)

    def test_plan_does_not_mutate_or_download(self):
        with patch.object(module, "download", side_effect=AssertionError("network")):
            report = self.capture(plan_only=True)
        self.assertEqual(report["status"], "planned")
        self.assertFalse(self.staging.exists())
        self.assertGreater(report["storage_peak_bytes"], self.body.stat().st_size)

    def test_mdoc_preview_delivers_linked_original_source_companion(self):
        self.capture()
        self.recipe['adapter'] = 'mdoc'
        self.recipe['selection'] = {'source_asset_id': 'original'}
        write(self.recipe_path, self.recipe)
        def render(recipe, sources, assets, output_dir, *, output_writer):
            target = output_dir / 'guide.html'
            output_writer(target, b'<a href="source.html">Original release and notices</a>')
            return {'guide': target}
        with patch('owl.acquisition.mdoc.render', side_effect=render):
            result = self.preview()
        receipt = json.loads(Path(result['receipt']).read_text())
        self.assertEqual([r['id'] for r in receipt['companions']], ['original'])
        original = self.staging / receipt['companions'][0]['relative_path']
        self.assertEqual(original.read_bytes(), self.body.read_bytes())
        self.assertEqual(original.name, 'source.html')

    def test_capture_observes_whole_hash_and_reuses_immutable_receipt(self):
        result = self.capture()
        self.assertFalse(result["content_ready"])
        self.assertEqual(result["status"], "awaiting_review")
        receipt_path = self.staging / "receipts/original.json"
        before = receipt_path.read_bytes()
        receipt = json.loads(before)
        self.assertEqual(receipt["sha256"], hashlib.sha256(self.body.read_bytes()).hexdigest())
        self.assertEqual(receipt["response_evidence"]["kind"], "local")
        self.assertEqual(receipt["verification"], "observed")
        with patch.object(module, "download", side_effect=AssertionError("network")):
            result = self.capture()
        self.assertEqual(result["reused_sources"], 1)
        self.assertEqual(receipt_path.read_bytes(), before)

    def test_changed_identity_and_corrupt_original_are_rejected(self):
        self.capture()
        self.document["sources"][0]["version"] = "2"
        write(self.manifest, self.document)
        with self.assertRaisesRegex(SafetyError, "different acquisition manifest"):
            self.capture()
        self.document["sources"][0]["version"] = "1"
        write(self.manifest, self.document)
        (self.staging / "sources/original").write_bytes(b"bad")
        with self.assertRaisesRegex(SafetyError, "changed"):
            self.capture()

    def test_source_pins_and_weak_checksum_are_verified(self):
        self.document["sources"][0]["publisher_checksums"]["md5"] = "0" * 32
        write(self.manifest, self.document)
        with self.assertRaisesRegex(SafetyError, "publisher checksum"):
            self.capture()
        self.assertFalse((self.staging / "receipts/original.json").exists())

    def test_manifest_duplicate_filters_and_unsafe_paths(self):
        duplicate = deepcopy(self.document["sources"][0]); duplicate["id"] = "different"
        self.document["sources"].append(duplicate)
        with self.assertRaisesRegex(SafetyError, "Duplicate"):
            module.normalize_manifest(self.document, allow_local=True)
        with self.assertRaisesRegex(SafetyError, "Requested resource"):
            self.capture(resource_ids=["unrelated"])
        with self.assertRaisesRegex(SafetyError, "profile"):
            self.capture(profile="small")
        self.staging = self.root / "LIBRARY" / "capture"
        with self.assertRaisesRegex(SafetyError, "production"):
            self.capture(plan_only=True)

    def test_unrelated_library_sibling_does_not_block_macos_path(self):
        # On macOS /LIBRARY exists because the OS directory is /Library.
        # An arbitrary sibling of that name is not OWL's production library.
        (self.root / "LIBRARY").mkdir()
        self.assertEqual(self.capture(plan_only=True)["status"], "planned")
        (self.root / "LIBRARY/BUILD_INFO.json").write_text("{}")
        with self.assertRaisesRegex(SafetyError, "production"):
            self.capture(plan_only=True)

    def test_real_free_space_and_separate_volume_are_checked(self):
        free = shutil.disk_usage(self.root)._replace(free=1)
        with patch.object(module.shutil, "disk_usage", return_value=free):
            with self.assertRaisesRegex(SafetyError, "free bytes"):
                self.capture(plan_only=True)
        with self.assertRaisesRegex(SafetyError, "different filesystem"):
            self.capture(plan_only=True, production_root=self.root)
        self.assertFalse(self.staging.exists())

    def test_capture_recovery_after_receipt_interruption(self):
        original = module.atomic_write
        def interrupted(path, data):
            if path.name == "original.json" and path.parent.name == "receipts":
                raise KeyboardInterrupt
            original(path, data)
        with patch.object(module, "atomic_write", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt): self.capture()
        with patch.object(module, "download", side_effect=AssertionError("network")):
            result = self.capture()
        self.assertEqual(result["status"], "awaiting_review")
        receipt = json.loads((self.staging / "receipts/original.json").read_text())
        self.assertEqual(receipt["response_evidence"]["kind"], "local")

    def test_preview_new_phase_budget_canonical_output_and_review_binding(self):
        self.capture()
        frozen = (self.staging / "manifest.json").read_bytes()
        report = self.preview()
        self.assertFalse(report["content_ready"])
        output = self.staging / report["outputs"][0]["relative_path"]
        self.assertIn("<td>42</td>", output.read_text())
        self.assertEqual(frozen, (self.staging / "manifest.json").read_bytes())
        # Production destinations yield the identical generated bytes.
        from owl.acquisition import documents
        manifest, receipts = module.load_capture_sources(self.staging)
        source = {**self.document["sources"][0]["fullasset_metadata"], **self.document["sources"][0], **receipts[0]}
        assets = {"original": source, "guide": json.loads(self.assets_path.read_text())["assets"][0]}
        normal = documents.render(self.recipe, {"original": self.staging / "sources/original"}, assets, self.root / "normal")
        self.assertEqual(output.read_bytes(), normal["guide"].read_bytes())
        self.assertTrue(self.preview()["reused"])
        fragment_path = Path(report["candidate_fragment"])
        fragment = json.loads(fragment_path.read_text())
        self.assertEqual(fragment["recipes"][0]["status"], "pending")
        reviewed = module.review(self.staging, fragment_path, evidence=["Read the full fixture and table"], resource_ids=["reference"])
        receipt = module.validate_review_binding(fragment, reviewed["receipt"])
        self.assertEqual(receipt["review"]["status"], "approved")
        fragment["assets"][0]["title"] = "Changed after review"
        with self.assertRaisesRegex(SafetyError, "exact captured fragment"):
            module.validate_review_binding(fragment, reviewed["receipt"])

    def test_preview_fails_before_writing_beyond_budget_and_recovers(self):
        self.capture()
        with self.assertRaisesRegex(SafetyError, "before writing"):
            module.preview(self.staging, self.recipe_path, self.assets_path, preview_bytes=1)
        self.assertFalse((self.staging / "previews/fixture/files/references/guide.html").exists())
        # A changed immutable phase declaration requires a new recipe identity.
        with self.assertRaisesRegex(SafetyError, "Immutable"):
            self.preview()

    def test_pinned_preview_preflight_counts_other_previews_before_rendering(self):
        from owl.acquisition import documents
        self.capture()
        other=self.staging/'previews/old/files/original.html'
        other.parent.mkdir(parents=True);other.write_bytes(b'x'*9000)
        templates=json.loads(self.assets_path.read_text())
        templates['assets'][0].update(size_bytes=2000,sha256='a'*64)
        write(self.assets_path,templates)
        with patch.object(documents,'render',side_effect=AssertionError('must preflight first')):
            with self.assertRaisesRegex(SafetyError,'combined preview_bytes before rendering'):self.preview()
        self.assertFalse((self.staging/'previews/fixture/files/references/guide.html').exists())

    def test_preview_control_metadata_is_rejected_before_peak_overrun(self):
        self.capture()
        peak = module.load_manifest(self.manifest, allow_local=True)["storage_peak_bytes"]
        templates = json.loads(self.assets_path.read_text())
        # An otherwise valid renderer ignores a large descriptive field, but
        # its portable candidate fragment must still fit the finite phase.
        templates["assets"][0]["description"] = "x" * (peak + 10000)
        write(self.assets_path, templates)
        with self.assertRaisesRegex(SafetyError, "metadata exceeds the storage peak before writing"):
            self.preview()
        self.assertFalse((self.staging / "previews/fixture/candidate-fragment.json").exists())
        self.assertFalse((self.staging / "previews/fixture/preview-receipt.json").exists())
        self.assertLess(module._usage(self.staging), peak)

    def test_interrupted_preview_reuses_output_and_preserves_source_capture(self):
        self.capture()
        original = module._immutable
        def interrupted(path, value):
            if path.name == "preview-receipt.json":
                raise KeyboardInterrupt
            return original(path, value)
        with patch.object(module, "_immutable", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt): self.preview()
        result = self.preview()
        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(self.capture()["reused_sources"], 1)
        fragment = json.loads(Path(result["candidate_fragment"]).read_text())
        fragment["recipes"][0]["selection"]["outputs"][0]["sections"][0]["expected_count"] = 2
        changed = write(self.root / "changed-recipe.json", fragment)
        with self.assertRaisesRegex(SafetyError, "preview transformation"):
            module.review(self.staging, changed, evidence=["Review cannot bind an unrendered selector"])

    def test_preview_and_review_scope_is_not_silently_ignored(self):
        self.capture()
        with self.assertRaisesRegex(SafetyError, "Requested resource"):
            self.preview(resource_ids=["elsewhere"])
        with self.assertRaisesRegex(SafetyError, "profile"):
            self.preview(profile="standard-512")
        report = self.preview()
        with self.assertRaisesRegex(SafetyError, "Requested resource"):
            module.review(self.staging, report["candidate_fragment"], evidence=["reviewed"], resource_ids=["elsewhere"])

    def test_review_rejects_changed_pins_missing_provenance_and_changed_output(self):
        capture = self.capture()
        fragment = json.loads(Path(capture["candidate_fragment"]).read_text())
        fragment["assets"][0].pop("acquisition_provenance")
        changed = write(self.root / "changed.json", fragment)
        with self.assertRaisesRegex(SafetyError, "provenance"):
            module.review(self.staging, changed, evidence=["reviewed"])
        report = self.preview()
        output = self.staging / report["outputs"][0]["relative_path"]
        output.write_text("tampered")
        with self.assertRaisesRegex(SafetyError, "Preview output changed"):
            module.review(self.staging, report["candidate_fragment"], evidence=["reviewed"])

    def test_review_rejects_source_receipt_changes_after_preview(self):
        self.capture()
        result = self.preview()
        receipt_path = self.staging / "receipts/original.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["response_evidence"] = {"kind": "unavailable"}
        write(receipt_path, receipt)
        with self.assertRaisesRegex(SafetyError, "changed source receipts"):
            module.review(self.staging, result["candidate_fragment"], evidence=["Changed transport evidence cannot be admitted"])

    def test_review_resource_alias_enforces_the_same_scope_as_stage(self):
        report = self.capture()
        fragment = json.loads(Path(report["candidate_fragment"]).read_text())
        fragment.pop("resource_updates")
        fragment["proposed_resource_updates"] = [{"id": "unrelated", "status": "ready",
            "review": {"status": "approved", "full_scope": True, "evidence": ["Unrelated assertion"]}}]
        altered = write(self.root / "alias.json", fragment)
        with self.assertRaisesRegex(SafetyError, "outside the requested scope"):
            module.review(self.staging, altered, evidence=["Review only reference"], resource_ids=["reference"])

    def test_review_selects_explicit_preview_revision_with_reused_output_id(self):
        self.capture()
        old = self.preview()
        self.recipe["id"] = "fixture-v2"
        self.recipe["selection"]["outputs"][0]["intro"] = "Revised edition context"
        write(self.recipe_path, self.recipe)
        templates = json.loads(self.assets_path.read_text())
        templates["assets"][0]["generation"]["recipe_id"] = "fixture-v2"
        write(self.assets_path, templates)
        new = self.preview()
        self.assertNotEqual(old["outputs"][0]["sha256"], new["outputs"][0]["sha256"])
        reviewed = module.review(self.staging, new["candidate_fragment"], evidence=["Read revised edition"])
        receipt = json.loads(Path(reviewed["receipt"]).read_text())
        self.assertEqual(receipt["artifacts"]["guide"]["preview_id"], "fixture-v2")
        self.assertEqual(receipt["artifacts"]["guide"]["sha256"], new["outputs"][0]["sha256"])

    def test_preview_file_directory_collision_is_rejected_before_body_write(self):
        self.capture()
        self.recipe["output_asset_ids"].append("other")
        output = deepcopy(self.recipe["selection"]["outputs"][0]); output["asset_id"] = "other"
        self.recipe["selection"]["outputs"].append(output)
        write(self.recipe_path, self.recipe)
        templates = json.loads(self.assets_path.read_text())
        other = deepcopy(templates["assets"][0]); other.update(id="other", destination="references/guide.html/other.html")
        templates["assets"].append(other)
        write(self.assets_path, templates)
        with self.assertRaisesRegex(SafetyError, "destination collision"):
            self.preview()
        self.assertFalse((self.staging / "previews/fixture/files").exists())

    def test_preview_reserves_companion_partial_paths_before_copying(self):
        image = self.root / "image.png"
        import base64
        image.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg=="))
        self.document["sources"].append({"id": "image", "resource_ids": ["reference"], "source_url": image.as_uri(),
            "version": "1", "size_bytes": image.stat().st_size, "metadata_evidence": [{"url": "https://publisher.test/meta", "sha256": "a" * 64}],
            "fullasset_metadata": {"format": "png", "destination": "references/image.png", "title": "Figure", "license": "CC0"}})
        self.document["budget"]["download_bytes"] += image.stat().st_size
        write(self.manifest, self.document)
        self.capture()
        self.recipe["source_asset_ids"].append("image")
        self.recipe["selection"]["dependencies"] = {"https://publisher.test/image.png": "image"}
        write(self.recipe_path, self.recipe)
        templates = json.loads(self.assets_path.read_text())
        templates["assets"][0]["destination"] = "references/image.png.part"
        write(self.assets_path, templates)
        with self.assertRaisesRegex(SafetyError, "destination collision"):
            self.preview()
        self.assertFalse((self.staging / "previews/fixture/files").exists())

    def test_local_reuse_preserves_official_identity_and_rejects_pin_mismatch(self):
        source = self.document["sources"][0]
        source["source_url"] = "https://publisher.test/frozen.html"
        source["sha256"] = hashlib.sha256(self.body.read_bytes()).hexdigest()
        write(self.manifest, self.document)
        local = write(self.root / "local.json", {"original": str(self.body)})
        with patch.object(module, "download", side_effect=AssertionError("No HTTP for a verified local original")):
            report = self.capture(local_manifest=local)
        self.assertEqual(report["local_copies"], 1)
        receipt = json.loads((self.staging / "receipts/original.json").read_text())
        self.assertEqual(receipt["source_url"], source["source_url"])
        self.assertEqual(receipt["response_evidence"]["kind"], "local_reuse")
        self.staging = self.root / "bad-local"
        source["sha256"] = "0" * 64
        write(self.manifest, self.document)
        with self.assertRaisesRegex(SafetyError, "Local reuse source SHA256"):
            self.capture(local_manifest=local)
        self.assertFalse((self.staging / "sources/original").exists())

    def test_acquisition_job_snapshots_local_reuse_mapping(self):
        self.document["sources"][0].update(source_url="https://publisher.test/frozen.html",
            sha256=hashlib.sha256(self.body.read_bytes()).hexdigest())
        write(self.manifest, self.document)
        local = write(self.root / "local.json", {"original": str(self.body)})
        jobdir = self.root / "local-job"
        jobs.start_acquisition_job(self.manifest, self.staging, job_dir=jobdir, reserve_bytes=0, local_manifest=local)
        write(local, {"original": "/invalid/edited-mapping"})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = jobs.status_job(jobdir)
            if state["state"] in jobs.TERMINAL and not state["worker_active"]: break
            time.sleep(.03)
        else:
            jobs.cancel_job(jobdir)
            self.fail("Local acquisition worker did not finish")
        wait_for_windows_process_exit(state.get("pid"))
        self.assertEqual(state["state"], "awaiting_review", jobs.logs_job(jobdir))
        recipe = json.loads((jobdir / "recipe.json").read_text())
        copied = Path(recipe["acquisition"]["kwargs"]["local_manifest"])
        self.assertTrue(copied.is_relative_to(jobdir / "snapshot"))
        self.assertEqual(json.loads(copied.read_text()), {"original": str(self.body)})
        self.assertEqual(json.loads((jobdir / "result.json").read_text())["local_copies"], 1)

    def test_acquisition_job_snapshots_and_finishes_awaiting_review(self):
        jobdir = self.root / "job"
        # Starting a job snapshots code plus the manifest, while bodies remain
        # acquired by the shared downloader in its owned staging directory.
        state = jobs.start_acquisition_job(self.manifest, self.staging, job_dir=jobdir, allow_local=True, reserve_bytes=0)
        self.document["sources"][0]["version"] = "edited after snapshot"
        write(self.manifest, self.document)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = jobs.status_job(jobdir)
            if state["state"] in jobs.TERMINAL and not state["worker_active"]: break
            time.sleep(.03)
        else:
            jobs.cancel_job(jobdir)
            self.fail("Acquisition worker did not finish")
        wait_for_windows_process_exit(state.get("pid"))
        self.assertEqual(state["state"], "awaiting_review", jobs.logs_job(jobdir))
        self.assertFalse(json.loads((jobdir / "result.json").read_text())["content_ready"])
        self.assertEqual(json.loads((self.staging / "manifest.json").read_text())["sources"][0]["version"], "1")
        with self.assertRaisesRegex(SafetyError, "review"):
            jobs.resume_job(jobdir)


@unittest.skipUnless(importlib.util.find_spec("libzim"), "optional libzim extra missing")
class CaptureZimTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.original = self.root / "production/LIBRARY/ZIM/fixture.zim"
        self.original.parent.mkdir(parents=True)
        from owl.build import _owned_directory
        _owned_directory(self.original.parent.parent / ".owl")
        from libzim.writer import Creator, Item, StringProvider, Hint
        class Entry(Item):
            def __init__(self, name, mime, body): self.name, self.mime, self.body = name, mime, body
            def get_path(self): return self.name
            def get_title(self): return self.name
            def get_mimetype(self): return self.mime
            def get_contentprovider(self): return StringProvider(self.body)
            def get_hints(self): return {Hint.FRONT_ARTICLE: self.mime == "text/html"}
        with Creator(self.original) as creator:
            creator.add_item(Entry("A/Guide", "text/html", '<html><body><h1>Complete procedure</h1><p>Original notice</p><img src="../images/figure.png" alt="Figure"></body></html>'))
            creator.add_item(Entry("images/figure.png", "image/png", b"tiny fixture image"))
            creator.add_item(Entry("A/Warning", "text/html", '<html><body><p>Instruction</p><img src="missing.png"></body></html>'))
            creator.set_mainpath("A/Guide")
        self.asset = {"id": "archive", "title": "Fixture", "category": "reference", "format": "zim",
            "source_url": "https://publisher.test/fixture.zim", "version": "1", "license": "CC-BY-4.0",
            "redistributable": True, "destination": "ZIM/fixture.zim", "attribution": "Fixture author",
            "size_bytes": self.original.stat().st_size, "sha256": hashlib.sha256(self.original.read_bytes()).hexdigest()}
        self.document = {"schema_version": 1, "kind": "acquisition", "id": "fixture", "profile": "full-1tb",
            "sources": [{"id": "archive", "source_url": self.asset["source_url"], "version": "1",
                "resource_ids": ["reference"], "size_bytes": self.asset["size_bytes"], "sha256": self.asset["sha256"],
                "metadata_evidence": [{"url": "https://publisher.test/meta", "sha256": "a" * 64}], "fullasset_metadata": self.asset}],
            "budget": {"download_bytes": self.asset["size_bytes"], "expanded_bytes": 0, "preview_bytes": 0, "scratch_bytes": 0, "cache_bytes": 0}}
        self.manifest = write(self.root / "capture.json", self.document)
        self.local = write(self.root / "local.json", {"archive": str(self.original)})
        self.staging = self.root / "quarantine"
        self.recipe = {"id": "fixture-zim", "resource_id": "reference", "adapter": "zim_direct", "version": "1",
            "source_asset_ids": ["archive"], "output_asset_ids": [], "workspace_bytes": 262144,
            "selection": {"source_asset_id": "archive", "entries": ["A/Guide"], "max_bytes": 100000,
                          "max_files": 3, "max_item_bytes": 65536}, "blockers": [], "review": {"status": "pending", "evidence": []}}
        self.recipe_path = write(self.root / "recipe.json", self.recipe)
        self.assets_path = write(self.root / "assets.json", {"assets": []})

    def preview(self):
        return module.preview(self.staging, self.recipe_path, self.assets_path, preview_bytes=100000,
                              scratch_bytes=262144, progress=lambda _: None)

    def test_zim_discovers_pinned_pending_outputs_without_touching_production_lock(self):
        from owl.runtime import file_lock
        with file_lock(self.original.parent.parent / ".owl/build.lock"):
            report = module.capture(self.manifest, self.staging, reserve_bytes=0, local_manifest=self.local, progress=lambda _: None)
            result = self.preview()
        self.assertEqual(report["body_downloads"], 0)
        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(len(result["outputs"]), 2)
        self.assertFalse(result["blockers"])
        self.assertTrue(self.preview()["reused"])
        fragment = json.loads(Path(result["candidate_fragment"]).read_text())
        recipe = fragment["recipes"][0]
        self.assertEqual(recipe["review"]["status"], "pending")
        self.assertEqual(set(recipe["output_asset_ids"]), set(recipe["selection"]["output_paths"]))
        self.assertTrue(all(a["source_url"] == self.asset["source_url"] for a in fragment["assets"]))
        # Execute the production renderer from the discovered contract: pins
        # must be identical, including attribution and local figure links.
        from owl.acquisition.runtime import Generator
        generator = Generator(self.root / "normal/LIBRARY", [self.asset, *fragment["assets"]], {recipe["id"]: recipe}, lambda _: None,
                              source_paths={"archive": self.staging / "sources/archive"})
        for asset in fragment["assets"]:
            target = generator.target / asset["destination"]
            self.assertEqual(generator.materialize(asset, target), asset["sha256"])
        reviewed = module.review(self.staging, result["candidate_fragment"], evidence=["Reviewed fixture text, figure and notice"])
        module.validate_review_binding(fragment, reviewed["receipt"])

    def test_zim_warnings_stay_explicit_and_bounds_fail_closed(self):
        module.capture(self.manifest, self.staging, reserve_bytes=0, local_manifest=self.local, progress=lambda _: None)
        self.recipe["selection"]["entries"] = ["A/Warning"]
        write(self.recipe_path, self.recipe)
        result = self.preview()
        self.assertTrue(result["blockers"])
        fragment = json.loads(Path(result["candidate_fragment"]).read_text())
        self.assertEqual(fragment["recipes"][0]["blockers"], result["blockers"])
        fragment["recipes"][0]["blockers"] = []
        altered = write(self.root / "cleared-warning.json", fragment)
        with self.assertRaisesRegex(SafetyError, "warnings remain required"):
            module.review(self.staging, altered, evidence=["Warnings cannot silently disappear"])
        self.recipe["id"] = "tiny-bound"
        self.recipe["selection"].update(entries=["A/Guide"], max_files=1)
        write(self.recipe_path, self.recipe)
        from owl.export_direct import ExportError
        with self.assertRaisesRegex(ExportError, "max-files"):
            module.preview(self.staging, self.recipe_path, self.assets_path, preview_bytes=200000,
                           scratch_bytes=524288, progress=lambda _: None)
        self.assertFalse((self.staging / "previews/tiny-bound/preview-receipt.json").exists())


class ResponseEvidenceTests(unittest.TestCase):
    def test_successful_get_evidence_retains_transport_identity(self):
        body = b"whole body"
        class Response(io.BytesIO):
            status = 200
            url = "https://cdn.publisher.test/edition.pdf"
            headers = {"Content-Length": str(len(body)), "ETag": '"edition-one"', "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"}
        with tempfile.TemporaryDirectory() as temp, patch("owl.download.urlopen", return_value=Response(body)):
            evidence = []
            result = download({"id": "source", "source_url": "https://publisher.test/edition.pdf", "size_bytes": len(body), "sha256": None},
                              Path(temp).resolve() / "source", repo_root=Path(temp).resolve(), progress=lambda _: None, response_evidence=evidence.append)
        self.assertEqual(result, hashlib.sha256(body).hexdigest())
        self.assertEqual(evidence[0]["final_url"], Response.url)
        self.assertEqual(evidence[0]["etag"], '"edition-one"')
        self.assertEqual(evidence[0]["content_length"], str(len(body)))
        self.assertEqual(evidence[0]["offset"], 0)


if __name__ == "__main__": unittest.main()
