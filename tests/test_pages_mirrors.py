import hashlib
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

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
