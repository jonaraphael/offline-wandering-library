import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import build_pages


class PagesMirrorTests(unittest.TestCase):
    def test_relay_minute_limit_and_documented_free_request_budget(self):
        directory = build_pages.ROOT / "relay"
        config = tomllib.loads((directory / "wrangler.toml").read_text(encoding="utf-8"))
        binding = next(binding for binding in config["ratelimits"] if binding["name"] == "REQUEST_LIMIT")
        self.assertEqual(binding["simple"], {"limit": 3 * 600, "period": 60})
        readme = (directory / "README.md").read_text(encoding="utf-8")
        self.assertIn("100,000 requests per day", readme)
        part = 4 * 2**20
        for size, label in [(16, "16 GB"), (64, "64 GB"), (256, "256 GB"), (1000, "1 TB")]:
            num_bytes = size * 10**9
            requests = (num_bytes + part - 1) // part
            self.assertIn(f"| {label} | ⌈{num_bytes:,} ÷ {part:,}⌉ | {requests:,} |", readme)

    def test_locked_publisher_failure_blocks_publication_and_verified_cache_recovers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = b"exact pinned bytes"
            digest = hashlib.sha256(source).hexdigest()
            (root / "pages-mirrors.json").write_text(json.dumps({"guide": digest}))
            asset = {"id": "guide", "status": "resolved", "redistributable": True,
                     "size_bytes": len(source), "sha256": digest, "source_url": "https://example.test/guide"}
            cache = root / "cache"
            site = root / "site"
            site.mkdir()
            with patch.object(build_pages, "SOURCE", root), patch.object(
                    build_pages, "urlopen", side_effect=TimeoutError("publisher offline")):
                with self.assertRaisesRegex(ValueError, "Required Pages mirror guide is unavailable"):
                    build_pages.publish_locked_mirrors({"guide": asset}, site, cache, 0)
                (cache / digest).write_bytes(source)
                files = build_pages.publish_locked_mirrors({"guide": asset}, site, cache, 0)
                self.assertEqual(files["guide"][0]["sha256"], digest)
                self.assertEqual((site / "mirrors/guide-0.bin").read_bytes(), source)

    def test_cold_build_recovers_only_matching_parts_from_the_previous_deployment(self):
        source = b"abcdef"
        digest = hashlib.sha256(source).hexdigest()
        asset = {"id": "guide", "status": "resolved", "redistributable": True,
                 "size_bytes": len(source), "sha256": digest, "source_url": "https://publisher.test/guide"}
        base = "https://pages.test/owl/"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "pages-mirrors.json").write_text(json.dumps({"guide": digest}))
            site = root / "site"
            site.mkdir()
            cache = root / "cache"
            contents = {"guide-0.bin": b"abcd", "guide-1.bin": b"ef"}

            def fetch(request, **kwargs):
                url = request.full_url
                if url == asset["source_url"]:
                    raise TimeoutError("publisher offline")
                self.assertTrue(url.startswith(base + "mirrors/"))
                stream = BytesIO(contents[url.rsplit("/", 1)[-1]])
                stream.status, stream.url = 200, url
                return stream

            with (patch.object(build_pages, "SOURCE", root), patch.object(build_pages, "PUBLISH_PART", 4),
                  patch.object(build_pages, "urlopen", side_effect=fetch)):
                files = build_pages.publish_locked_mirrors({"guide": asset}, site, cache, 0, published_base=base)
                self.assertEqual([file["bytes"] for file in files["guide"]], [4, 2])
                self.assertEqual((cache / digest).read_bytes(), source)
                (cache / digest).unlink()
                contents["guide-1.bin"] = b"zz"
                with self.assertRaisesRegex(ValueError, "published mirror SHA-256 differs"):
                    build_pages.publish_locked_mirrors({"guide": asset}, site, cache, 0, published_base=base)
                self.assertEqual(list(cache.iterdir()), [])

    def test_new_mirror_retries_publisher_denials_with_browser_headers(self):
        source = b"pinned"
        url = "https://publisher.test/guide"
        digest = hashlib.sha256(source).hexdigest()
        asset = {"source_url": url, "sha256": digest, "size_bytes": len(source)}
        response = BytesIO(source)
        response.status, response.url = 200, url
        with (tempfile.TemporaryDirectory() as folder,
              patch.object(build_pages, "urlopen", side_effect=[HTTPError(url, 403, "Forbidden", {}, None), response]) as fetch):
            result = build_pages.verified_source(asset, Path(folder))
            self.assertEqual(result.read_bytes(), source)
        request = fetch.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), build_pages.BROWSER_USER_AGENT)
        self.assertIsNone(request.get_header("Origin"))
