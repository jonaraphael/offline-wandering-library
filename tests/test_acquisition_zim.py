"""The recipe wrapper preserves a real ZIM export's layout, pins and locks."""
import base64
from copy import deepcopy
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from owl.acquisition.runtime import Generator
from owl.build import _owned_directory
from owl.catalog import CatalogError
from owl.export_direct import export_zim
from owl.runtime import file_lock
from owl.safety import sha256_file


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF2QAAAAASUVORK5CYII=")


@unittest.skipUnless(importlib.util.find_spec("libzim"), "optional libzim extra missing")
class AcquisitionZimTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.target = self.root / "drive/LIBRARY"
        self.source = self.target / "ZIM/OTHER/fixture.zim"
        self.source.parent.mkdir(parents=True)
        _owned_directory(self.target / ".owl")
        from libzim.writer import Creator, Hint, Item, StringProvider

        class Fixture(Item):
            def __init__(self, name, mime, content):
                self.name, self.mime, self.content = name, mime, content
            def get_path(self): return self.name
            def get_title(self): return self.name
            def get_mimetype(self): return self.mime
            def get_contentprovider(self): return StringProvider(self.content)
            def get_hints(self): return {Hint.FRONT_ARTICLE: self.mime == "text/html"}

        with Creator(self.source) as creator:
            creator.add_item(Fixture("A/Guide", "text/html", '<html><body><h1>Illustrated reference</h1>'
                '<p>Original source author and CC BY 4.0 notice.</p>'
                '<img src="../images/diagram.png" alt="Original diagram"></body></html>'))
            creator.add_item(Fixture("images/diagram.png", "image/png", PNG))
            creator.set_mainpath("A/Guide")
        self.source_asset = dict(id="archive", title="Illustrated reference archive", category="reference", format="zim",
            source_url="https://example.invalid/fixture.zim", destination="ZIM/OTHER/fixture.zim", version="1",
            size_bytes=self.source.stat().st_size, sha256=sha256_file(self.source), license="CC-BY-4.0",
            redistributable=True, required=True, profiles=[], reader_required=True,
            attribution="Original fixture authors; preserve the original notice.")
        report = export_zim(self.source, self.root / "review", source_asset=self.source_asset,
            entries=["A/Guide"], export_id="reviewed-zim", max_bytes=100000, max_files=2, progress=lambda _: None)
        self.assertFalse(report["requires_review"])
        self.outputs = []
        for row in report["assets"]:
            identity = "guide" if row["source_archive_entry"] == "A/Guide" else "diagram"
            self.outputs.append({**row, "id": identity, "source_url": self.source_asset["source_url"],
                                 "generation": {"recipe_id": "reviewed-zim"}})
        self.assets = [self.source_asset, *self.outputs]
        self.recipe = dict(id="reviewed-zim", resource_id="reference", adapter="zim_direct", version="1",
            source_asset_ids=["archive"], output_asset_ids=[a["id"] for a in self.outputs],
            selection={"source_asset_id": "archive", "entries": ["A/Guide"],
                       "output_paths": {a["id"]: a["destination"] for a in self.outputs}},
            workspace_bytes=100000, review={"status": "approved", "evidence": ["Reviewed tiny fixture"]}, blockers=[])

    def test_real_recipe_retains_image_notices_relative_layout_and_held_lock(self):
        generator = Generator(self.target, self.assets, {self.recipe["id"]: self.recipe}, lambda _: None)
        with file_lock(self.target / ".owl/build.lock"):
            for output in self.outputs:
                destination = self.target / output["destination"]
                self.assertEqual(generator.materialize(output, destination), output["sha256"])
                self.assertEqual(sha256_file(destination), output["sha256"])
        guide = next(a for a in self.outputs if a["id"] == "guide")
        path = self.target / guide["destination"]
        html = path.read_text(encoding="utf-8")
        self.assertIn("Original source author and CC BY 4.0 notice", html)
        self.assertIn("Original fixture authors", html)
        self.assertIn("source edition", html.lower())

        class Images(HTMLParser):
            def __init__(self):
                super().__init__()
                self.sources = []
            def handle_starttag(self, tag, attrs):
                if tag == "img": self.sources.append(dict(attrs)["src"])

        images = Images()
        images.feed(html)
        self.assertEqual(len(images.sources), 1)
        src = urlsplit(images.sources[0])
        self.assertFalse(src.scheme)
        self.assertEqual((path.parent / unquote(src.path)).read_bytes(), PNG)

    def test_recipe_refuses_relocated_output_before_export(self):
        outputs = deepcopy(self.outputs)
        outputs[0]["destination"] = "REFERENCE/relocated/output.html"
        generator = Generator(self.target, [self.source_asset, *outputs], {self.recipe["id"]: self.recipe}, lambda _: None)
        with patch("owl.export_direct.export_zim", side_effect=AssertionError("Do not export a broken layout")):
            with self.assertRaisesRegex(CatalogError, "preserve reviewed export paths"):
                generator.materialize(outputs[0], self.target / outputs[0]["destination"])


if __name__ == "__main__":
    unittest.main()
