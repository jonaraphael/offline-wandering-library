"""Missing publishers may not hide independent captures or create false completeness."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from owl.acquisition import capture as capture_module
from owl.download import DownloadError, MissingSourceError, download
from owl.safety import SafetyError


class Response(io.BytesIO):
    def __init__(self, body, url, *, status=200, headers=None):
        super().__init__(body)
        self.url, self.status = url, status
        self.headers = {"Content-Length": str(len(body)), **(headers or {})}


class MissingSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.staging = self.root / "capture"
        self.manifest = self.root / "manifest.json"
        self.body = b"frozen complete fixture"
        self.calls = []
        self.document = {"schema_version": 1, "kind": "acquisition", "id": "fixture",
            "sources": [{"id": identity, "resource_ids": [identity],
                "source_url": "https://publisher.test/" + identity, "version": "frozen-1",
                "size_bytes": len(self.body), "sha256": hashlib.sha256(self.body).hexdigest(),
                "publisher_checksums": {"md5": hashlib.md5(self.body).hexdigest()},
                "metadata_evidence": [{"url": "https://publisher.test/metadata", "sha256": "a" * 64}],
                "fullasset_metadata": {"title": identity, "format": "html", "destination": identity + ".html"}}
                for identity in ("before", "missing", "after")],
            "budget": {"download_bytes": 3 * len(self.body), "expanded_bytes": 0, "preview_bytes": 0,
                       "scratch_bytes": 0, "cache_bytes": 0}}
        self.save_manifest()

    def save_manifest(self):
        self.manifest.write_text(json.dumps(self.document))

    def capture(self, **kwargs):
        return capture_module.capture(self.manifest, self.staging, reserve_bytes=0,
                                      progress=lambda _: None, **kwargs)

    def open(self, request, **kwargs):
        self.calls.append(request.full_url)
        if request.full_url.endswith("/missing"):
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        return Response(self.body, request.full_url)

    def test_opt_in_continues_404_but_cannot_be_complete_or_admitted(self):
        frozen = self.manifest.read_bytes()
        with patch("owl.download.urlopen", side_effect=self.open):
            with self.assertRaises(capture_module.IncompleteCaptureError) as raised:
                self.capture(continue_missing_sources=True)
        report = raised.exception.report
        self.assertEqual(self.calls, [row["source_url"] for row in self.document["sources"]])
        self.assertEqual((report["status"], report["captured_source_count"], report["missing_source_count"]),
                         ("incomplete", 2, 1))
        self.assertFalse(report["complete"])
        self.assertFalse(report["content_ready"])
        self.assertNotIn("candidate_fragment", report)
        self.assertFalse((self.staging / "candidate-fragment.json").exists())
        self.assertFalse((self.staging / "receipts/missing.json").exists())
        self.assertEqual(json.loads((self.staging / "capture-report.json").read_text()), report)
        self.assertEqual(self.manifest.read_bytes(), frozen)
        self.assertEqual(report["exceptions"][0]["http_status"], 404)
        with self.assertRaisesRegex(SafetyError, "incomplete"):
            capture_module.load_capture_sources(self.staging)

    def test_default_stops_at_missing_and_keeps_existing_checkpoint(self):
        with patch("owl.download.urlopen", side_effect=self.open):
            with self.assertRaises(DownloadError):
                self.capture()
        self.assertEqual(len(self.calls), 2)
        self.assertTrue((self.staging / "receipts/before.json").is_file())
        self.assertFalse((self.staging / "exceptions").exists())
        self.assertFalse((self.staging / "sources/after").exists())

    def test_resume_preserves_receipt_missing_record_and_partial_download(self):
        class InterruptedResponse(Response):
            def read(self, size=-1):
                if self.tell():
                    raise KeyboardInterrupt
                return super().read(5)

        def interrupted(request, **kwargs):
            if request.full_url.endswith("/after"):
                self.calls.append(request.full_url)
                return InterruptedResponse(self.body, request.full_url)
            return self.open(request, **kwargs)

        with patch("owl.download.urlopen", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.capture(continue_missing_sources=True)
        receipt = self.staging / "receipts/before.json"
        exception = self.staging / "exceptions/missing.json"
        old_receipt, old_exception = receipt.read_bytes(), exception.read_bytes()
        self.assertEqual((self.staging / "sources/after.part").read_bytes(), self.body[:5])
        self.calls.clear()

        def resumed(request, **kwargs):
            self.calls.append(request.full_url)
            self.assertTrue(request.full_url.endswith("/after"))
            self.assertEqual(request.headers["Range"], "bytes=5-")
            return Response(self.body[5:], request.full_url, status=206,
                            headers={"Content-Range": f"bytes 5-{len(self.body)-1}/{len(self.body)}"})

        with patch("owl.download.urlopen", side_effect=resumed):
            with self.assertRaises(capture_module.IncompleteCaptureError) as raised:
                self.capture(continue_missing_sources=True)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(raised.exception.report["reused_sources"], 1)
        self.assertEqual(receipt.read_bytes(), old_receipt)
        self.assertEqual(exception.read_bytes(), old_exception)
        self.assertEqual((self.staging / "sources/after").read_bytes(), self.body)
        with patch("owl.download.urlopen", side_effect=AssertionError("must not retry")):
            with self.assertRaises(capture_module.IncompleteCaptureError):
                self.capture(continue_missing_sources=True)
            with self.assertRaisesRegex(SafetyError, "explicit --continue-missing-sources"):
                self.capture()

    def test_checksum_size_and_publisher_checksum_failures_are_not_skipped(self):
        for mode in ("sha256", "size", "publisher"):
            with self.subTest(mode=mode):
                self.staging = self.root / mode
                source = self.document["sources"][0]
                original = deepcopy(source)
                if mode == "publisher":
                    source["publisher_checksums"]["md5"] = "0" * 32
                self.save_manifest()
                self.calls.clear()

                def rejected(request, **kwargs):
                    self.calls.append(request.full_url)
                    body = b"x" * len(self.body) if mode == "sha256" else self.body
                    return Response(body, request.full_url,
                                    headers={"Content-Length": str(len(body) + 1)} if mode == "size" else None)

                with patch("owl.download.urlopen", side_effect=rejected):
                    with self.assertRaises((DownloadError, SafetyError)) as raised:
                        self.capture(continue_missing_sources=True)
                self.assertNotIsInstance(raised.exception, capture_module.IncompleteCaptureError)
                self.assertEqual(len(self.calls), 1)
                self.assertFalse((self.staging / "exceptions").exists())
                self.assertFalse((self.staging / "receipts/before.json").exists())
                self.document["sources"][0] = original

    def test_saved_exception_identity_and_receipt_collision_are_rejected(self):
        with patch("owl.download.urlopen", side_effect=self.open):
            with self.assertRaises(capture_module.IncompleteCaptureError):
                self.capture(continue_missing_sources=True)
        path = self.staging / "exceptions/missing.json"
        original = json.loads(path.read_text())
        for key, value in (("manifest_sha256", "b" * 64), ("source_record_sha256", "b" * 64),
                           ("http_status", 403), ("requested_url", "https://other.test/")):
            path.write_text(json.dumps({**original, key: value}))
            with patch("owl.download.urlopen", side_effect=AssertionError("network")):
                with self.assertRaisesRegex(SafetyError, "exception differs"):
                    self.capture(continue_missing_sources=True)
        path.write_text(json.dumps(original))
        (self.staging / "sources/missing").write_bytes(self.body)
        with self.assertRaisesRegex(SafetyError, "conflicts"):
            self.capture(continue_missing_sources=True)

    def test_report_exceptions_are_bounded_with_all_details_on_disk(self):
        def missing(request, **kwargs):
            raise HTTPError(request.full_url, 410, "gone", {}, None)
        with patch("owl.download.urlopen", side_effect=missing) as opened, \
                patch.object(capture_module, "MAX_REPORT_EXCEPTIONS", 1):
            with self.assertRaises(capture_module.IncompleteCaptureError) as raised:
                self.capture(continue_missing_sources=True)
        self.assertEqual(opened.call_count, 3)
        self.assertEqual(raised.exception.report["missing_source_count"], 3)
        self.assertEqual(len(raised.exception.report["exceptions"]), 1)
        self.assertEqual(raised.exception.report["exceptions_omitted"], 2)
        self.assertEqual(len(list((self.staging / "exceptions").glob("*.json"))), 3)


class MissingDownloadTests(unittest.TestCase):
    def test_opt_in_missing_has_no_retry_mirror_or_error_body_read(self):
        class Unreadable(io.BytesIO):
            def read(self, *args):
                raise AssertionError("missing response body must not be downloaded")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            asset = {"id": "fixture", "source_url": "https://publisher.test/fixture",
                     "mirrors": ["https://mirror.test/fixture"], "size_bytes": 5, "sha256": None}
            for status in (404, 410):
                body = Unreadable(b"error")
                error = HTTPError(asset["source_url"], status, "missing", {}, body)
                with patch("owl.download.urlopen", side_effect=error) as opened:
                    with self.assertRaises(MissingSourceError) as raised:
                        download(asset, root / "source", repo_root=root, stop_on_missing=True,
                                 sleep=lambda _: self.fail("must not retry"))
                self.assertEqual(opened.call_count, 1)
                self.assertEqual(raised.exception.http_status, status)
                self.assertTrue(body.closed)
                self.assertFalse((root / "source.part").exists())

    def test_opt_in_never_reclassifies_other_http_errors_as_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            asset = {"id": "fixture", "source_url": "https://publisher.test/fixture",
                     "size_bytes": 5, "sha256": None}
            for status in (403, 429, 500):
                with patch("owl.download.urlopen", side_effect=HTTPError(asset["source_url"], status, "failed", {}, None)):
                    with self.assertRaises(DownloadError) as raised:
                        download(asset, root / "source", repo_root=root, stop_on_missing=True,
                                 retries=0, progress=lambda _: None)
                self.assertNotIsInstance(raised.exception, MissingSourceError)


if __name__ == "__main__":
    unittest.main()
