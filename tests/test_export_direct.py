"""Small real ZIMs exercise direct export, illustrations, integrity and resume."""
from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from owl.catalog import load_catalog
from owl.export_direct import export_zim, ExportError, BLOCK
from owl.safety import SafetyError, sha256_file


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF2QAAAAASUVORK5CYII=")


@unittest.skipUnless(importlib.util.find_spec("libzim"), "optional libzim extra missing")
class DirectExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.drive = self.root / "ssd"
        self.target = self.drive / "LIBRARY"
        self.target.mkdir(parents=True)
        self.source = self.target / "source.zim"
        self.items = {
            "A/Start": ("text/html", '<html><head><link rel="stylesheet" href="../styles/main.css"></head><body>'
                       '<h1 id="overview">Pump diagram</h1><p>pumpbodyunique</p>'
                       '<img src="../images/pump.png" alt="Pump"><img srcset="../images/pump.png 1x" alt="Responsive">'
                       '<img src="../images/chart.svg"><a href="Next#part">Next selected article</a>'
                       '<a href="Unselected">Other archive article</a>'
                       '<script src="https://example.invalid/run.js">bad()</script>'
                       '<form action="https://example.invalid/send"><input name="secret"></form>'
                       '<img src="https://example.invalid/tracker.png" onerror="bad()">'
                       '<p>Original author attribution and CC BY 4.0 notice.</p></body></html>'),
            "A/Next": ("text/html", '<h1 id="part">Second page</h1><a href="Start">Back</a>'),
            "A/Unselected": ("text/html", '<h1>Not requested</h1>'),
            "styles/main.css": ("text/css", '@import "more.css"; @font-face {font-family:x;src:url("../fonts/x.woff2")} body{background-image:url("../images/pump.png")}'),
            "styles/more.css": ("text/css", 'p{color:navy}'),
            "images/pump.png": ("image/png", PNG),
            "fonts/x.woff2": ("font/woff2", b"test-font-bytes"),
            "images/chart.svg": ("image/svg+xml", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="blue"/><script>bad()</script></svg>'),
        }
        self.make_archive()

    def make_archive(self):
        from libzim.writer import Creator, Item, StringProvider, Hint
        class Fixture(Item):
            def __init__(self, name, mime, content): self.name, self.mime, self.content = name, mime, content
            def get_path(self): return self.name
            def get_title(self): return self.name
            def get_mimetype(self): return self.mime
            def get_contentprovider(self): return StringProvider(self.content)
            def get_hints(self): return {Hint.FRONT_ARTICLE: self.mime == "text/html"}
        self.source.unlink(missing_ok=True)
        with Creator(self.source) as creator:
            for name, (mime, body) in self.items.items(): creator.add_item(Fixture(name, mime, body))
            creator.add_redirection("A/Alias", "Alias", "A/Start", {})
            creator.set_mainpath("A/Start")
        self.asset = {"id": "fixture", "title": "Reference fixture", "category": "mechanical", "format": "zim",
                      "source_url": "https://example.invalid/fixture.zim", "destination": "ZIM/OTHER/fixture.zim",
                      "version": "2026-01", "size_bytes": self.source.stat().st_size,
                      "sha256": sha256_file(self.source), "license": "CC-BY-4.0", "redistributable": True,
                      "required": False, "profiles": [], "reader_required": True,
                      "attribution": "Fixture authors. Retain the original notice."}

    def export(self, **options):
        options.setdefault("entries", ["A/Start", "A/Next"])
        options.setdefault("max_bytes", 20 * BLOCK)
        options.setdefault("max_files", 30)
        options.setdefault("progress", lambda _: None)
        return export_zim(self.source, self.drive, source_asset=self.asset, **options)

    def test_real_html_images_styles_fonts_and_links_with_notices(self):
        report = self.export()
        self.assertEqual(report["documents"], 2)
        byname = {a["source_archive_entry"]: a for a in report["assets"]}
        self.assertNotIn("A/Unselected", byname)
        self.assertEqual(len(byname), 7)
        for name in ["images/pump.png", "fonts/x.woff2"]:
            self.assertEqual((self.target / byname[name]["destination"]).read_bytes(), self.items[name][1])
        html = (self.target / byname["A/Start"]["destination"]).read_text()
        self.assertIn("Original author attribution", html)
        self.assertIn("Fixture authors", html)
        self.assertIn("source edition", html.lower())
        self.assertIn("Content-Security-Policy", html)
        self.assertNotIn("<script", html)
        self.assertNotIn("<form", html)
        self.assertNotIn("onerror", html)
        self.assertNotIn("https://example.invalid/tracker.png", html)
        self.assertNotIn("https://example.invalid/run.js", html)
        self.assertIn("#part", html)
        self.assertIn("srcset=", html)
        svg = ET.fromstring((self.target / byname["images/chart.svg"]["destination"]).read_text())
        self.assertEqual(svg.attrib["viewBox"], "0 0 10 10")
        self.assertEqual(len(svg), 1)
        class Links(HTMLParser):
            links = []
            def handle_starttag(self, tag, attrs):
                for k, v in attrs:
                    if k in {"href", "src"} and v: self.links.append(v)
        links = Links(); links.feed(html)
        page = self.target / byname["A/Start"]["destination"]
        for url in links.links:
            self.assertFalse(urlsplit(url).scheme)
            self.assertTrue((page.parent / unquote(urlsplit(url).path)).exists(), url)
        catalog = self.target / ".owl/exports/fixture/catalog.yaml"
        imported = load_catalog(catalog, allow_local=True)
        self.assertEqual(len(imported), 7)
        self.assertTrue(all(a["derived_from_asset_id"] == "fixture" for a in imported))
        self.assertTrue(all(a["source_url"].startswith("file:") and not a["reader_required"] for a in imported))
        self.assertTrue(all(sha256_file(self.target / a["destination"]) == a["sha256"] for a in imported))

    def test_alias_dedup_and_all_selects_documents_not_unsupported_data(self):
        r = self.export(entries=["A/Alias", "A/Start"])
        self.assertEqual(r["selected_entries"], ["A/Start"])
        other = self.root / "other"; other.mkdir()
        r = export_zim(self.source, other, source_asset=self.asset, all_articles=True,
                       max_bytes=20*BLOCK, max_files=30, progress=lambda _: None)
        self.assertEqual(r["documents"], 3)

    def test_all_stops_at_file_cap_without_loading_million_entry_payloads(self):
        class Item:
            mimetype = "text/html"
            @property
            def content(self): raise AssertionError("Payload must not be loaded during selection")
        class Entry:
            is_redirect = False
            def __init__(self, path): self.path = path
            def get_item(self): return Item()
        class HugeArchive:
            all_entry_count = 1_000_000
            examined = 0
            def __init__(self, _): pass
            def _get_entry_by_id(self, number):
                self.examined += 1
                self.assert_bounded()
                return Entry(f"A/document-{number}")
            def assert_bounded(self):
                if self.examined > 100001: raise AssertionError("Enumeration exceeded file ceiling")
            def has_entry_by_path(self, _): return True
            def get_entry_by_path(self, path): return Entry(path)
        tracemalloc.start()
        try:
            with patch("libzim.reader.Archive", HugeArchive):
                with self.assertRaisesRegex(ExportError, "Selection exceeds --max-files"):
                    export_zim(self.source, self.drive, source_asset=self.asset, all_articles=True,
                               max_bytes=BLOCK, max_files=100000, progress=lambda _: None)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 64*BLOCK)
        self.assertFalse((self.target / ".owl/exports/fixture/catalog.yaml").exists())

    def test_unicode_paths_titles_and_checkpoint_resume_use_utf8(self):
        self.items["A/Eau_électricité_日本語"] = ("text/html", "<h1>Eau et électricité 水</h1>")
        self.make_archive()
        self.asset["title"] = "Électricité et eau 水"
        self.asset["attribution"] = "Auteurs : Zoë et équipe 日本語"
        report = self.export(entries=["A/Eau_électricité_日本語"])
        original_read = Path.read_text
        def windows_read(path, *args, **kwargs):
            if path.name in {"state.json", "owner.json"} and "exports" in path.parts:
                self.assertEqual(kwargs.get("encoding"), "utf-8")
            return original_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", windows_read):
            again = self.export(entries=["A/Eau_électricité_日本語"])
        self.assertEqual(report, again)
        html = (self.target / report["assets"][0]["destination"]).read_text(encoding="utf-8")
        self.assertIn("électricité 水", html)
        self.assertIn("Zoë et équipe 日本語", html)

    def test_resume_reuses_verified_outputs_and_repairs_owned_corruption(self):
        r = self.export()
        first = self.target / r["assets"][0]["destination"]
        first.write_bytes(b"corrupt")
        messages = []
        r2 = self.export(progress=messages.append)
        self.assertEqual(r["assets"], r2["assets"])
        self.assertTrue(any(m.startswith("REUSE ") for m in messages))
        self.assertEqual(sha256_file(first), r["assets"][0]["sha256"])

    def test_image_links_and_svg_embedded_images_keep_local_illustrations(self):
        self.items["A/Start"] = ("text/html", '<a href="../images/pump.png">Full-size diagram</a>'
                                 '<img src="../images/chart.svg">')
        self.items["images/chart.svg"] = ("image/svg+xml", '<svg xmlns="http://www.w3.org/2000/svg" '
                                          'xmlns:xlink="http://www.w3.org/1999/xlink">'
                                          '<image xlink:href="pump.png" width="1" height="1"/></svg>')
        self.make_archive()
        report = self.export(entries=["A/Start"])
        byname = {a["source_archive_entry"]: a for a in report["assets"]}
        self.assertIn("images/pump.png", byname)
        svg = ET.fromstring((self.target / byname["images/chart.svg"]["destination"]).read_bytes())
        self.assertIn("{http://www.w3.org/1999/xlink}href", svg[0].attrib)

    def test_external_license_links_survive_without_active_remote_loads(self):
        self.items["A/Start"] = ("text/html", '<p>Licensed <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a></p>'
                                 '<link rel="stylesheet" href="https://example.invalid/style.css">')
        self.make_archive()
        report = self.export(entries=["A/Start"])
        html = (self.target / report["assets"][0]["destination"]).read_text()
        self.assertIn('href="https://creativecommons.org/licenses/by/4.0/"', html)
        self.assertIn('Original source link; requires internet', html)
        self.assertNotIn('href="https://example.invalid/style.css"', html)

    def test_active_markup_cannot_restore_scripts_or_remote_resource_loads(self):
        self.items["A/Start"] = ("text/html", '<BASE href="https://example.invalid/">'
                                 '<meta http-equiv="refresh" content="0;url=https://example.invalid/">'
                                 '<a href="&#106;avascript:bad()">Bad link</a>'
                                 '<iframe srcdoc="&lt;script&gt;bad()&lt;/script&gt;">hidden</iframe>'
                                 '<svg><foreignObject><script>bad()</script></foreignObject>'
                                 '<rect onload="bad()" width="10" height="10"/></svg>'
                                 '<p style="background:url(https://example.invalid/tracker)">Readable</p>'
                                 '<img srcset="https://example.invalid/tracker 1x, ../images/pump.png 2x">'
                                 '<img src="https://example.invalid/unavailable" alt="Missing diagram">'
                                 '<img src="https://example.invalid/tracker">')
        self.make_archive()
        report = self.export(entries=["A/Start"])
        page = next(a for a in report["assets"] if a["export_document"])
        html = (self.target / page["destination"]).read_text(encoding="utf-8")
        class Markup(HTMLParser):
            def __init__(self): super().__init__(); self.tags = []; self.attributes = []
            def handle_starttag(self, tag, attrs): self.tags.append(tag); self.attributes.extend(attrs)
        parsed = Markup(); parsed.feed(html)
        self.assertFalse(set(parsed.tags) & {"script", "iframe", "base", "foreignobject"})
        for key, value in parsed.attributes:
            self.assertFalse(key.startswith("on"))
            if key in {"href", "src", "srcset", "style"}:
                self.assertNotIn("javascript:", value or "")
                self.assertNotIn("https://example.invalid/", value or "")
        self.assertIn("Readable", html)
        self.assertNotIn("hidden", html)
        self.assertEqual(parsed.tags.count("img"), 1)
        self.assertIn("[Offline image unavailable: Missing diagram]", html)
        self.assertTrue(any(a["source_archive_entry"] == "images/pump.png" for a in report["assets"]))

    def test_owned_bad_output_is_not_replaced_before_readback_verifies(self):
        report = self.export()
        asset = report["assets"][0]
        destination = self.target / asset["destination"]
        destination.write_bytes(b"previous-file")
        real_hash = sha256_file
        def bad_readback(path):
            return "0" * 64 if path.suffix == ".part" else real_hash(path)
        with patch("owl.export_direct.sha256_file", side_effect=bad_readback):
            with self.assertRaisesRegex(ExportError, "readback checksum failed"):
                self.export()
        self.assertEqual(destination.read_bytes(), b"previous-file")
        self.assertFalse((self.target / ".owl/exports/fixture/catalog.yaml").exists())

    def test_resume_rejects_changed_selection_and_allows_increased_limits(self):
        with self.assertRaisesRegex(ExportError, "max-bytes"):
            self.export(max_bytes=10)
        self.export()
        with self.assertRaisesRegex(ExportError, "Checkpoint source/selection"):
            self.export(entries=["A/Start"])
        changed = dict(self.asset, version="another edition")
        with self.assertRaisesRegex(ExportError, "Checkpoint source/selection"):
            export_zim(self.source, self.drive, source_asset=changed, entries=["A/Start", "A/Next"],
                       max_bytes=20 * BLOCK, max_files=30, progress=lambda _: None)

    def test_corrupted_partial_prefix_restarts_and_produces_pinned_output(self):
        self.items = {"A/Start": ("text/plain", b"x" * (2*BLOCK + 31))}
        self.make_archive()
        def stop(message):
            if message.startswith("WRITE "): raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.export(entries=["A/Start"], progress=stop)
        part = next((self.target / ".owl/exports/fixture/parts").glob("*.part"))
        with part.open("r+b") as stream: stream.write(b"bad")
        messages = []
        report = self.export(entries=["A/Start"], progress=messages.append)
        counts = [int(m.rsplit(" ", 1)[1].split("/")[0]) for m in messages if m.startswith("WRITE ")]
        self.assertEqual(counts[0], BLOCK)
        self.assertEqual((self.target / report["assets"][0]["destination"]).read_bytes(), self.items["A/Start"][1])

    def test_interrupt_retains_partial_no_manifest_and_resumes_suffix(self):
        self.items = {"A/Start": ("text/plain", b"x" * (3*BLOCK + 31))}
        self.make_archive()
        def stop(message):
            if message.startswith("WRITE "): raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt): self.export(entries=["A/Start"], progress=stop)
        private = self.target / ".owl/exports/fixture"
        self.assertFalse((private / "catalog.yaml").exists())
        part = next((private / "parts").glob("*.part"))
        self.assertEqual(part.stat().st_size, BLOCK)
        state = json.loads((private / "state.json").read_text())
        self.assertFalse(state["complete"])
        writes = []
        self.export(entries=["A/Start"], progress=writes.append)
        counts = [int(m.rsplit(" ", 1)[1].split("/")[0]) for m in writes if m.startswith("WRITE ")]
        self.assertEqual(counts[0], 2*BLOCK)
        self.assertFalse(part.exists())

    def test_limits_and_disk_space_fail_without_completed_manifest(self):
        for kwargs, regex in [({"max_bytes": 50}, "max-bytes"), ({"max_files": 2}, "max-files"),
                              ({"max_item_bytes": 10}, "max-item-bytes")]:
            with self.subTest(kwargs=kwargs):
                target = self.root / ("limit-" + next(iter(kwargs))); target.mkdir()
                with self.assertRaisesRegex(ExportError, regex):
                    export_zim(self.source, target, source_asset=self.asset, entries=["A/Start"],
                               max_bytes=kwargs.get("max_bytes", 20*BLOCK), max_files=kwargs.get("max_files", 30),
                               max_item_bytes=kwargs.get("max_item_bytes", 16*BLOCK), progress=lambda _: None)
                self.assertFalse((target / ".owl/exports/fixture/catalog.yaml").exists())
        with patch("owl.export_direct.shutil.disk_usage", return_value=type("Space", (), {"free": 0})()):
            with self.assertRaisesRegex(ExportError, "Insufficient"): self.export()

    def test_bad_source_pin_and_changed_source_are_rejected(self):
        self.asset["sha256"] = "0" * 64
        with self.assertRaisesRegex(ExportError, "SHA-256 mismatch"): self.export()
        self.asset["sha256"] = sha256_file(self.source)
        def change(message):
            if message.startswith("WRITE "):
                with self.source.open("ab") as stream: stream.write(b"changed")
        with self.assertRaisesRegex(ExportError, "changed during export"): self.export(progress=change)
        self.assertFalse((self.target / ".owl/exports/fixture/catalog.yaml").exists())

    def test_unowned_collision_symlink_and_case_alias_refused(self):
        key = hashlib.sha256(b"A/Start").hexdigest()
        output = self.target / f"REFERENCE/DIRECT/fixture/{key[:2]}/{key}.html"
        output.parent.mkdir(parents=True)
        output.write_text("unrelated")
        with self.assertRaisesRegex(SafetyError, "unrelated"): self.export()
        self.assertEqual(output.read_text(), "unrelated")
        output.unlink()
        output.symlink_to(self.source)
        with self.assertRaises(SafetyError): self.export()
        output.unlink()
        # A differently cased tree must not alias the planned path on exFAT.
        (self.target / "REFERENCE").rename(self.target / "reference")
        with self.assertRaisesRegex(SafetyError, "Case-conflicting"): self.export()

    def test_archive_traversal_and_oversize_dependency_fail_safely(self):
        self.items["../evil"] = ("text/html", "bad")
        self.make_archive()
        with self.assertRaisesRegex(ExportError, "Traversal"): self.export(entries=["../evil"])
        self.items.pop("../evil")
        self.items["images/pump.png"] = ("image/png", b"x" * (2*BLOCK))
        self.make_archive()
        with self.assertRaisesRegex(ExportError, "max-item-bytes"): self.export(max_item_bytes=BLOCK)
        self.assertFalse((self.target / ".owl/exports/fixture/catalog.yaml").exists())

    def test_target_replacement_does_not_write_into_new_mountpoint(self):
        moved = self.root / "disconnected"
        def disconnect(message):
            if message.startswith("WRITE "):
                self.target.rename(moved)
                self.target.mkdir()
        with self.assertRaises((SafetyError, OSError)):
            self.export(progress=disconnect)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertTrue(list((moved / ".owl/exports/fixture/parts").glob("*.part")))

    def test_complete_export_can_be_indexed_without_archive(self):
        from owl.search import build_search
        r = self.export()
        docs = [a for a in r["assets"] if a["export_document"]]
        search = build_search(self.target, docs)
        self.assertTrue(all(a["status"] == "full_text" for a in search["assets"]))


if __name__ == "__main__":
    unittest.main()
