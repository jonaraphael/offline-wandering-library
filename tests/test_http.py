"""Downloader integration tests against an actual loopback HTTP server."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener

from owl.download import DownloadError, download


@contextmanager
def loopback_server(payload: bytes, *, mode: str = "range"):
    """Serve deterministic byte ranges, errors, or a deliberately short body.

    HTTP responses are real. Only proxy discovery is disabled so ambient proxy
    settings cannot send a loopback test through any external service.
    """
    requests = []
    cut = 1024 * 1024 + 17

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_GET(self):
            request = {
                "range": self.headers.get("Range"),
                "if_range": self.headers.get("If-Range"),
                "accept_encoding": self.headers.get("Accept-Encoding"),
            }
            requests.append(request)
            body = payload
            offset = 0
            status = 200
            if mode == "corrupt":
                body = bytes([payload[0] ^ 0xFF]) + payload[1:]
            if request["range"] and mode != "ignore_range":
                offset = int(request["range"].removeprefix("bytes=").removesuffix("-"))
                if mode == "reject_range" or offset >= len(body):
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{len(body)}")
                    self.send_header("Content-Length", "0")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    return
                status = 206
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body) - offset))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", '"fixture-v1"')
            self.send_header("Connection", "close")
            if status == 206:
                self.send_header("Content-Range", f"bytes {offset}-{len(body) - 1}/{len(body)}")
            self.end_headers()
            if mode == "truncate_first" and len(requests) == 1:
                # Advertise the complete length but close after a known prefix.
                # No sleeps, races, or time-dependent connection termination.
                body = body[:cut]
            self.wfile.write(body[offset:])
            self.wfile.flush()
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        opener = build_opener(ProxyHandler({}))
        with patch("owl.download.urlopen", opener.open):
            yield f"http://127.0.0.1:{server.server_address[1]}/fixture", requests, cut
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise RuntimeError("Loopback HTTP server failed to stop")


class HTTPDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.destination = self.root / "asset"
        self.part = self.root / "asset.part"
        self.partial_metadata = self.root / "asset.part.json"
        self.payload = (bytes(range(256)) * (8192 + 1))[:2 * 1024 * 1024 + 127]
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def fetch(self, url, *, checksum="pinned", retries=1):
        asset = {
            "id": "http-fixture",
            "source_url": url,
            "size_bytes": len(self.payload),
            "sha256": self.digest if checksum == "pinned" else None,
        }
        return download(
            asset,
            self.destination,
            repo_root=self.root,
            retries=retries,
            timeout=3,
            sleep=lambda _: None,
            progress=lambda _: None,
        )

    def test_truncated_body_resumes_using_real_http_range(self):
        with loopback_server(self.payload, mode="truncate_first") as (url, requests, cut):
            digest = self.fetch(url)
        self.assertEqual(digest, self.digest)
        self.assertEqual(self.destination.read_bytes(), self.payload)
        self.assertEqual(len(requests), 2)
        self.assertIsNone(requests[0]["range"])
        self.assertEqual(requests[1]["range"], f"bytes={cut}-")
        self.assertEqual(requests[1]["if_range"], '"fixture-v1"')
        self.assertEqual(requests[1]["accept_encoding"], "identity")
        self.assertFalse(self.part.exists())
        self.assertFalse(self.partial_metadata.exists())

    def test_unpinned_resume_uses_matching_server_validator(self):
        with loopback_server(self.payload, mode="truncate_first") as (url, requests, cut):
            digest = self.fetch(url, checksum=None)
        self.assertEqual(digest, self.digest)
        self.assertEqual(self.destination.read_bytes(), self.payload)
        self.assertEqual(requests[1]["range"], f"bytes={cut}-")
        self.assertEqual(requests[1]["if_range"], '"fixture-v1"')

    def test_server_ignoring_range_restarts_instead_of_appending(self):
        self.part.write_bytes(b"outdated prefix that must be discarded")
        initial_size = self.part.stat().st_size
        with loopback_server(self.payload, mode="ignore_range") as (url, requests, _):
            self.fetch(url, retries=0)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["range"], f"bytes={initial_size}-")
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_range_416_is_an_error_and_preserves_existing_file(self):
        previous = b"previous verified version"
        partial = self.payload[:103]
        self.destination.write_bytes(previous)
        self.part.write_bytes(partial)
        with loopback_server(self.payload, mode="reject_range") as (url, requests, _):
            with self.assertRaisesRegex(DownloadError, "416"):
                self.fetch(url, retries=0)
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.destination.read_bytes(), previous)
        self.assertEqual(self.part.read_bytes(), partial)

    def test_complete_pinned_partial_is_verified_without_an_http_request(self):
        self.part.write_bytes(self.payload)
        with loopback_server(self.payload, mode="reject_range") as (url, requests, _):
            self.assertEqual(self.fetch(url, retries=0), self.digest)
        self.assertEqual(requests, [])
        self.assertEqual(self.destination.read_bytes(), self.payload)
        self.assertFalse(self.part.exists())

    def test_bad_checksum_never_overwrites_existing_destination(self):
        previous = b"retain the previous verified version"
        self.destination.write_bytes(previous)
        with loopback_server(self.payload, mode="corrupt") as (url, requests, _):
            with self.assertRaisesRegex(DownloadError, "SHA-256 mismatch"):
                self.fetch(url, retries=0)
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.destination.read_bytes(), previous)
        self.assertFalse(self.part.exists())
        self.assertFalse(self.partial_metadata.exists())


if __name__ == "__main__":
    unittest.main()
