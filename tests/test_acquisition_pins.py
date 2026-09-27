import base64
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request

from owl.acquisition.metadata import _MetadataRedirect
from owl.acquisition.model import AcquisitionError
from owl.acquisition.pins import (HeadRedirect, PinProbe, header_sha256, probe_manifest,
                                  sidecar_sha256, stackoverflow_input_candidates)


URL = "https://publisher.example/edition.pdf"
SHA = "12" * 32
B64 = base64.b64encode(bytes.fromhex(SHA)).decode()


class Response:
    status = 200

    def __init__(self, headers=None, url=URL):
        self.headers = headers or {"Content-Length": "123", "Repr-Digest": "sha-256=:" + B64 + ":"}
        self.url = url

    def geturl(self):
        return self.url

    def read(self, *args):
        raise AssertionError("Resource body must never be read")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class SourcePinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name).resolve()

    def test_header_digest_and_cached_offline_replay(self):
        def opener(request, **kwargs):
            self.assertEqual(request.get_method(), "HEAD")
            return Response()
        first = PinProbe(self.cache, opener=opener).probe({"id": "test", "url": URL})
        self.assertEqual((first["status"], first["size_bytes"], first["sha256"]), ("proposed", 123, SHA))
        second = PinProbe(self.cache, offline=True, opener=lambda *a, **k: self.fail("Network called")).probe(
            {"id": "test", "url": URL})
        self.assertEqual(second["sha256"], SHA)
        self.assertTrue(second["evidence"][0]["cached"])

    def test_redirect_keeps_head_and_rejects_http(self):
        redirect = HeadRedirect()
        request = Request(URL, method="HEAD")
        self.assertEqual(redirect.redirect_request(request, None, 302, "", {}, URL + "?new=1").get_method(), "HEAD")
        with self.assertRaises(AcquisitionError):
            redirect.redirect_request(request, None, 302, "", {}, "http://publisher.example/edition.pdf")

    def test_redirect_does_not_drain_body_and_bounds_hops(self):
        class Unreadable(BytesIO):
            def read(self, *a):
                raise AssertionError("Redirect body read")
        class Parent:
            def open(self, request, **kwargs):
                self.request = request
                return Response()
        redirect = HeadRedirect()
        redirect.parent = Parent()
        request = Request(URL, method="HEAD")
        request.timeout = 25
        fp = Unreadable(b"not metadata")
        redirect.http_error_302(request, fp, 302, "", {"Location": "/new.pdf"})
        self.assertTrue(fp.closed)
        self.assertEqual(redirect.parent.request.get_method(), "HEAD")
        self.assertEqual(redirect.parent.request.full_url, "https://publisher.example/new.pdf")
        request._owl_redirect_hops = 5
        with self.assertRaises(AcquisitionError):
            redirect.http_error_302(request, Unreadable(), 302, "", {"Location": "/new.pdf"})

    def test_metadata_redirect_does_not_drain_and_keeps_body_boundary(self):
        class Unreadable(BytesIO):
            def read(self, *a):
                raise AssertionError("Metadata redirect body read")
        class Parent:
            def open(self, request, **kwargs):
                self.request = request
                return Response()
        redirect = _MetadataRedirect()
        redirect.parent = Parent()
        request = Request("https://publisher.example/list.json")
        request.timeout = 25
        fp = Unreadable(b"arbitrarily large redirect body")
        redirect.http_error_302(request, fp, 302, "", {"Location": "/current.json"})
        self.assertTrue(fp.closed)
        self.assertEqual(redirect.parent.request.full_url, "https://publisher.example/current.json")
        self.assertEqual(redirect.parent.request.get_method(), "GET")
        for url in ["/source.pdf", "http://publisher.example/current.json"]:
            fp = Unreadable()
            with self.assertRaises(AcquisitionError):
                redirect.http_error_302(request, fp, 302, "", {"Location": url})
            self.assertTrue(fp.closed)
        request._owl_metadata_redirect_hops = 5
        with self.assertRaises(AcquisitionError):
            redirect.http_error_302(request, Unreadable(), 302, "", {"Location": "/current.json"})

    def test_weak_and_composite_checksums_are_not_sha256(self):
        for headers in [{"ETag": '"' + SHA + '"'}, {"Digest": "md5=" + B64},
                        {"Content-Digest": "sha-256=:" + B64 + ":"},
                        {"x-amz-checksum-sha256": B64},
                        {"x-amz-checksum-sha256": B64 + "-2", "x-amz-checksum-type": "COMPOSITE"}]:
            self.assertIsNone(header_sha256(headers))
        self.assertEqual(header_sha256({"x-amz-checksum-sha256": B64, "x-amz-checksum-type": "FULL_OBJECT"}), SHA)

    def test_sidecar_exact_filename_and_ambiguity(self):
        sidecar = URL + ".sha256"
        self.assertEqual(sidecar_sha256((SHA + " *edition.pdf\n").encode(), source=URL, checksum_url=sidecar), SHA)
        self.assertEqual(sidecar_sha256(("SHA256 (edition.pdf) = " + SHA).encode(), source=URL, checksum_url=sidecar), SHA)
        self.assertEqual(sidecar_sha256(SHA.encode(), source=URL, checksum_url=sidecar), SHA)
        for text, url in [(SHA + " other.pdf", sidecar), (SHA, "https://publisher.example/SHA256SUMS"),
                          (SHA + " edition.pdf\n" + "34" * 32 + " edition.pdf", sidecar)]:
            with self.assertRaises(AcquisitionError):
                sidecar_sha256(text.encode(), source=URL, checksum_url=url)

    def test_changed_pin_and_size_are_pending(self):
        probe = PinProbe(self.cache, opener=lambda *a, **k: Response())
        for expected in ({"expected_sha256": "34" * 32}, {"expected_size_bytes": 124}):
            result = probe.probe({"id": "x", "url": URL, **expected})
            self.assertEqual(result["status"], "pending")
            self.assertIsNone(result["sha256"])
            self.assertIn("changed", result["blockers"][0])

    def test_changed_size_is_reported_when_sha256_is_absent(self):
        probe = PinProbe(self.cache, opener=lambda *a, **k: Response({"Content-Length": "124"}))
        result = probe.probe({"id": "x", "url": URL, "expected_size_bytes": 123})
        self.assertEqual(result["size_bytes"], 124)
        self.assertEqual(len(result["blockers"]), 2)
        self.assertIn("changed", result["blockers"][0])

    def test_sidecar_probe_and_conflicting_digest(self):
        class Sidecar:
            evidence = [{"kind": "sha256-sidecar", "sha256": "ab" * 32}]
            def fetch(self, url, **kwargs):
                return (SHA + " *edition.pdf").encode()
        probe = PinProbe(self.cache, opener=lambda *a, **k: Response({"Content-Length": "123"}), fetcher=Sidecar())
        result = probe.probe({"id": "x", "url": URL, "checksum_url": URL + ".sha256"})
        self.assertEqual(result["sha256"], SHA)
        self.assertEqual(result["status"], "proposed")
        other = base64.b64encode(bytes.fromhex("34" * 32)).decode()
        probe = PinProbe(self.cache, refresh=True, opener=lambda *a, **k: Response(
            {"Content-Length": "123", "Digest": "sha-256=" + other}), fetcher=Sidecar())
        result = probe.probe({"id": "x", "url": URL, "checksum_url": URL + ".sha256"})
        self.assertEqual(result["status"], "pending")
        self.assertIn("disagree", result["blockers"][0])

    def test_partial_or_encoded_representation_rejected(self):
        for extra in ({"Content-Range": "bytes 0-1/123"}, {"Content-Encoding": "gzip"}):
            response = Response({"Content-Length": "123", "Digest": "sha-256=" + B64, **extra})
            probe = PinProbe(self.cache / str(len(extra)), refresh=True, opener=lambda *a, **k: response)
            result = probe.probe({"id": "x", "url": URL})
            self.assertEqual(result["status"], "pending")
            self.assertIsNone(result["size_bytes"])

    def test_http_error_is_recorded_without_reading_body(self):
        class Unreadable(BytesIO):
            def read(self, *a):
                raise AssertionError("HTTP error body read")
        def opener(request, **kwargs):
            raise HTTPError(URL, 403, "Denied", {"Content-Length": "17"}, Unreadable(b"error"))
        result = PinProbe(self.cache, opener=opener).probe({"id": "x", "url": URL})
        self.assertEqual(result["evidence"][0]["status"], 403)
        self.assertIsNone(result["size_bytes"])
        self.assertFalse(result["evidence"][0]["body_read"])

    def test_missing_offline_and_failed_connection_remain_pending(self):
        result = PinProbe(self.cache, offline=True).probe({"id": "x", "url": URL})
        self.assertEqual(result["status"], "pending")
        self.assertIn("No cached", result["blockers"][0])

    def test_manifest_filter_duplicate_and_limit(self):
        doc = {"schema_version": 1, "requests": [{"id": "a", "url": URL}, {"id": "b", "url": URL}]}
        probe = PinProbe(self.cache, opener=lambda *a, **k: Response())
        result = probe_manifest(doc, probe, ids=["b"])
        self.assertEqual([r["id"] for r in result["records"]], ["b"])
        self.assertEqual(result["proposed_count"], 1)
        with self.assertRaises(AcquisitionError):
            probe_manifest(doc, probe, ids=["absent"])
        doc["requests"].append(doc["requests"][0])
        with self.assertRaises(AcquisitionError):
            probe_manifest(doc, probe)

    def test_invalid_cache_fails_closed(self):
        probe = PinProbe(self.cache, opener=lambda *a, **k: Response())
        probe.probe({"id": "x", "url": URL})
        cache = next((self.cache / "head").glob("*.json"))
        record = json.loads(cache.read_text())
        record["body_read"] = True
        cache.write_text(json.dumps(record))
        result = PinProbe(self.cache, offline=True).probe({"id": "x", "url": URL})
        self.assertEqual(result["status"], "pending")
        self.assertIn("identity", result["blockers"][0])

    def test_archive_candidates_keep_all_four_roles_and_label_weak_hashes(self):
        files = [{"name": f"stackoverflow.com-{name}.7z", "source": "original", "size": "100",
                  "sha1": "ab" * 20, "md5": "cd" * 16} for name in ("Posts", "Comments", "Users", "PostLinks")]
        evidence = {"url": "https://archive.org/metadata/stackexchange", "sha256": "ef" * 32}
        result = stackoverflow_input_candidates({"files": files}, evidence)
        self.assertEqual(result["download_bytes"], 400)
        self.assertEqual({r["input_role"] for r in result["candidates"]}, {"posts", "comments", "users", "links"})
        self.assertTrue(all(r["sha256"] is None for r in result["candidates"]))
        with self.assertRaises(AcquisitionError):
            stackoverflow_input_candidates({"files": files[:-1]}, evidence)


if __name__ == "__main__":
    unittest.main()
