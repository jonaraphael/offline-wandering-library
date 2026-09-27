"""Synthetic EPUB conversion: content preservation, fixed output and safe inputs."""
from collections import Counter
from copy import deepcopy
import hashlib
from html import escape
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unicodedata
import unittest
from unittest.mock import patch
import zipfile
import zlib

from owl.acquisition import epub_pdf
from owl.acquisition.model import validate_recipes
from owl.acquisition.runtime import Generator, preflight_recipes, recipe_digest
from owl.safety import SafetyError


def _renderer_available():
    try:
        module = epub_pdf.preflight()
    except SafetyError:
        return False
    return module.VersionBind == epub_pdf.PYMUPDF_VERSION


def _png(width=80, height=120, *, rgba=None, rgb=(0, 102, 153)):
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    pixel = bytes(rgba) if rgba is not None else bytes(rgb)
    pixels = (b"\0" + pixel * width) * height
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6 if rgba is not None else 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def _recipe():
    return {
        "id": "epub-fixture", "resource_id": "reference", "adapter": "epub_pdf",
        "version": "1", "source_asset_ids": ["original"], "output_asset_ids": ["book"],
        "selection": {"outputs": {"book": "original"},
                      "pymupdf_version": epub_pdf.PYMUPDF_VERSION,
                      "layout": epub_pdf.LAYOUT.copy(),
                      "allowed_warnings": ["unknown epub version: 3.0"],
                      "trim_image_only_cover": True, "print_css": ""},
        "review": {"status": "approved", "evidence": ["Synthetic test EPUB"]},
        "blockers": [],
    }


class EPUBRecipeTests(unittest.TestCase):
    def test_recipe_rejects_unreviewed_layout_warning_or_renderer(self):
        changes = ({"layout": {"width": 600, "height": 800, "fontsize": 17}},
                   {"allowed_warnings": ["cannot load image"]},
                   {"pymupdf_version": "1.28.1"},
                   {"print_css": "body { display: none; }"},
                   {"illustration_policy": "unreviewed-layout"},
                   {"trim_image_only_cover": 1})
        for change in changes:
            with self.subTest(change=change):
                recipe = _recipe()
                recipe["selection"].update(change)
                with self.assertRaises(SafetyError):
                    validate_recipes([recipe])

    def test_recipe_requires_one_hidden_epub_per_pdf(self):
        assets = {"original": {"format": "epub", "supporting_file": True},
                  "book": {"format": "pdf"}}
        epub_pdf.validate_recipe(_recipe(), assets)
        for changed in ({"supporting_file": False}, {"format": "html"}):
            with self.subTest(changed=changed):
                invalid = deepcopy(assets)
                invalid["original"].update(changed)
                with self.assertRaisesRegex(SafetyError, "supporting EPUB"):
                    epub_pdf.validate_recipe(_recipe(), invalid)
        recipe = _recipe()
        recipe["dependency_asset_ids"] = ["extra"]
        with self.assertRaisesRegex(SafetyError, "own source EPUB"):
            epub_pdf.validate_recipe(recipe, assets)
        recipe = _recipe()
        recipe["output_asset_ids"].append("other")
        recipe["selection"]["outputs"]["other"] = "original"
        with self.assertRaisesRegex(SafetyError, "own source EPUB"):
            epub_pdf.validate_recipe(recipe)

    def test_preflight_requires_both_pymupdf_and_mupdf_versions(self):
        with patch.object(epub_pdf.importlib, "import_module", side_effect=ImportError):
            with self.assertRaisesRegex(SafetyError, "PyMuPDF==1.28.2"):
                preflight_recipes({"epub-fixture": _recipe()})
        for binding, engine in (("1.28.1", "1.28.2"), ("1.28.2", "1.28.1")):
            module = SimpleNamespace(VersionBind=binding, version=(binding, engine, ""))
            with self.subTest(binding=binding, engine=engine):
                with patch.object(epub_pdf.importlib, "import_module", return_value=module):
                    with self.assertRaisesRegex(SafetyError, "exact PyMuPDF/MuPDF"):
                        epub_pdf.preflight(_recipe())


@unittest.skipUnless(_renderer_available(), "Requires optional pinned PyMuPDF/MuPDF 1.28.2")
class EPUBPDFTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "original.epub"
        self.destination = self.root / "book.pdf"
        self.module = epub_pdf.preflight()
        self.recipe = _recipe()
        self.write_epub()

    def write_epub(self, *, body=None, cover_id="cover", cover_body=None, css="", extra=None,
                   repeat_chapter=False, chapter_class="", second_image=None, extra_images=None):
        if body is None:
            body = ('<h1>Chapter One</h1><p>Preserve every word, number 123 and punctuation.</p>'
                    '<img src="picture.png" width="64" height="96" alt="Chapter illustration"/>')
        if cover_body is None:
            cover_body = '<img src="picture.png" width="400" height="600" alt="Cover"/>'
        cover_path = cover_id + ".xhtml"
        repeated_spine = '<itemref idref="chapter"/>' if repeat_chapter else ""
        image_manifest = "".join(f'<item id="extra-image-{number}" href="{name}" media-type="image/png"/>'
                                 for number, name in enumerate(sorted(extra_images or {})))
        def page(title, content, body_class=""):
            body_tag = '<body class="' + escape(body_class, quote=True) + '">' if body_class else '<body>'
            return ('<html xmlns="http://www.w3.org/1999/xhtml"><head><title>' + title +
                    '</title><link rel="stylesheet" href="style.css"/></head>' + body_tag +
                    content + '</body></html>').encode()
        files = {
            "mimetype": b"application/epub+zip",
            "META-INF/container.xml": (b'<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                b'<rootfiles><rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/>'
                b'</rootfiles></container>'),
            "OPS/package.opf": ('<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book">'
                '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<dc:identifier id="book">urn:owl:synthetic-book</dc:identifier>'
                '<dc:title>Synthetic illustrated book</dc:title><dc:creator>Fixture Author</dc:creator>'
                '<dc:language>en</dc:language><dc:rights>Fixture notice must survive.</dc:rights>'
                '<meta property="dcterms:modified">2020-01-01T00:00:00Z</meta></metadata><manifest>'
                f'<item id="{cover_id}" href="{cover_path}" media-type="application/xhtml+xml"/>'
                '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
                '<item id="picture" href="picture.png" media-type="image/png" properties="cover-image"/>'
                + ('<item id="second-picture" href="second.png" media-type="image/png"/>' if second_image is not None else '') +
                image_manifest +
                '<item id="style" href="style.css" media-type="text/css"/>'
                '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
                f'</manifest><spine><itemref idref="{cover_id}"/><itemref idref="chapter"/>'
                f'{repeated_spine}</spine></package>').encode(),
            "OPS/" + cover_path: page("Cover", cover_body),
            "OPS/chapter.xhtml": page("Chapter One", body, chapter_class),
            "OPS/nav.xhtml": ('<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
                '<head><title>Contents</title></head><body><nav epub:type="toc"><ol>'
                f'<li><a href="{cover_path}">Cover</a></li>'
                '<li><a href="chapter.xhtml">Chapter One</a></li></ol></nav></body></html>').encode(),
            "OPS/style.css": css.encode(), "OPS/picture.png": _png(),
        }
        if second_image is not None:
            files["OPS/second.png"] = second_image
        files.update({"OPS/" + name: data for name, data in (extra_images or {}).items()})
        files.update(extra or {})
        with zipfile.ZipFile(self.source, "w") as archive:
            for name, data in files.items():
                archive.writestr(zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)), data)
        payload = self.source.read_bytes()
        self.assets = {
            "original": {"id": "original", "format": "epub", "supporting_file": True,
                         "destination": "REFERENCE/SOURCES/original.epub", "size_bytes": len(payload),
                         "sha256": hashlib.sha256(payload).hexdigest()},
            "book": {"id": "book", "format": "pdf", "destination": "REFERENCE/book.pdf",
                     "generation": {"recipe_id": "epub-fixture"}},
        }

    def convert(self, **options):
        options.setdefault("allowed_warnings", ["unknown epub version: 3.0"])
        return epub_pdf.convert(self.source, self.destination, **options)

    def test_deterministic_pdf_preserves_metadata_toc_text_images_and_original(self):
        original = self.source.read_bytes()
        before_stat = self.source.stat()
        first_report = self.convert()
        first = self.destination.read_bytes()
        self.assertEqual(self.convert(), first_report)
        self.assertEqual(self.destination.read_bytes(), first)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.source.stat().st_mtime_ns, before_stat.st_mtime_ns)
        self.assertEqual(first_report["spine_count"], 2)
        self.assertEqual(first_report["chapter_pages"], [1, 1])
        self.assertEqual(first_report["displayed_images"], 2)
        self.assertEqual(first_report["toc_entries"], 2)
        self.assertTrue(first_report["cover_trimmed"])
        self.assertEqual(first_report["sha256"], hashlib.sha256(first).hexdigest())
        with self.module.open(self.destination) as document:
            self.assertEqual(document.metadata["title"], "Synthetic illustrated book")
            self.assertEqual(document.metadata["author"], "Fixture Author")
            self.assertIn(epub_pdf.PDF_PROVENANCE, document.metadata["subject"])
            self.assertEqual(document.metadata["producer"], "OWL EPUB-to-PDF; PyMuPDF 1.28.2")
            self.assertEqual(document.metadata["creationDate"], "")
            self.assertEqual(document.metadata["modDate"], "")
            self.assertEqual(document.xref_get_key(-1, "ID"),
                             ("array", "[<" + "0" * 32 + "><" + "0" * 32 + ">]"))
            self.assertEqual(document.get_toc(), [[1, "Cover", 1], [1, "Chapter One", 2]])
            metadata = document.xref_get_key(document.pdf_catalog(), "OWLSourceEPUBMetadata")[1]
            self.assertIn("Fixture notice must survive.", metadata)
            self.assertEqual(document[0].rect, self.module.Rect(0, 0, 400, 600))
            self.assertEqual(document[1].rect, self.module.Rect(0, 0, 600, 800))
            self.assertEqual([len(page.get_image_info()) for page in document], [1, 1])
            self.assertIn("Preserve every word, number 123 and punctuation.", document[1].get_text())

    def test_cover_crop_requires_explicit_cover_and_empty_text(self):
        for parameters in ({"cover_id": "front"},
                           {"cover_body": '<p>Visible cover credit</p><img src="picture.png" width="200" height="300"/>'}):
            with self.subTest(parameters=parameters):
                self.write_epub(**parameters)
                self.assertFalse(self.convert()["cover_trimmed"])
                with self.module.open(self.destination) as document:
                    self.assertEqual(document[0].rect, self.module.Rect(0, 0, 600, 800))

    def test_transparent_png_survives_split_pdf_mask_deterministically(self):
        self.write_epub(extra={"OPS/picture.png": _png(rgba=(80, 140, 200, 128))})
        original = self.source.read_bytes()
        report = self.convert()
        output = self.destination.read_bytes()
        self.assertEqual(self.convert(), report)
        self.assertEqual(self.destination.read_bytes(), output)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(report["displayed_images"], 2)
        self.assertTrue(report["cover_trimmed"])
        with self.module.open(self.source) as source, self.module.open(self.destination) as pdf:
            source.layout(**epub_pdf.LAYOUT)
            self.assertEqual([len(page.get_image_info()) for page in pdf], [1, 1])
            # The EPUB image includes alpha, while PDF exposes RGB plus a soft mask.
            self.assertNotEqual(source[1].get_image_info(hashes=True)[0]["digest"],
                                pdf[1].get_image_info(hashes=True)[0]["digest"])
            image = next(block for block in pdf[1].get_text("dict")["blocks"] if block["type"] == 1)
            self.assertTrue(image["mask"])
            self.assertGreaterEqual(epub_pdf._transparent_images_preserved(self.module, source[1], pdf[1]), 0)

    def test_transparency_comparison_rejects_changed_alpha_or_colour_pixels(self):
        rectangle = self.module.Rect(40, 50, 120, 170)
        for changed in ((80, 140, 200, 127), (88, 140, 200, 128)):
            with self.subTest(changed=changed):
                with self.module.open() as first, self.module.open() as second:
                    before = first.new_page(width=600, height=800)
                    after = second.new_page(width=600, height=800)
                    before.insert_image(rectangle, stream=_png(rgba=(80, 140, 200, 128)))
                    after.insert_image(rectangle, stream=_png(rgba=changed))
                    with self.assertRaisesRegex(SafetyError, "changed image pixels"):
                        epub_pdf._transparent_images_preserved(self.module, before, after)

    def test_transparency_comparison_allows_only_one_premultiplied_colour_step(self):
        rectangle = self.module.Rect(40, 50, 120, 170)
        with self.module.open() as first, self.module.open() as second:
            before = first.new_page(width=600, height=800)
            after = second.new_page(width=600, height=800)
            before.insert_image(rectangle, stream=_png(rgba=(80, 140, 200, 128)))
            after.insert_image(rectangle, stream=_png(rgba=(82, 140, 200, 128)))
            self.assertEqual(epub_pdf._transparent_images_preserved(self.module, before, after), 1)

    def test_cover_crop_can_be_disabled(self):
        self.assertFalse(self.convert(trim_image_only_cover=False)["cover_trimmed"])
        with self.module.open(self.destination) as document:
            self.assertEqual(document[0].rect, self.module.Rect(0, 0, 600, 800))

    def test_cover_crop_requires_one_displayed_image_and_one_chapter_page(self):
        covers = [
            '<img src="picture.png" width="100" height="150"/><img src="picture.png" width="100" height="150"/>',
            '<img src="picture.png" width="448" height="672"/>' +
            '<p>Further cover material belongs to the same chapter.</p>' * 30,
        ]
        for number, markup in enumerate(covers):
            with self.subTest(number=number):
                self.write_epub(cover_body=markup)
                report = self.convert()
                self.assertFalse(report["cover_trimmed"])
                with self.module.open(self.destination) as document:
                    self.assertEqual(document[0].rect, self.module.Rect(0, 0, 600, 800))
                    if number == 0:
                        self.assertEqual(len(document[0].get_image_info()), 2)
                    else:
                        self.assertGreater(report["chapter_pages"][0], 1)
                        self.assertEqual(document[0].get_text().strip(), "")
                        self.assertEqual(len(document[0].get_image_info()), 1)

    def test_repeated_spine_reference_preserves_both_chapter_positions(self):
        self.write_epub(repeat_chapter=True)
        report = self.convert()
        self.assertEqual(report["spine_count"], 3)
        self.assertEqual(report["chapter_pages"], [1, 1, 1])
        self.assertEqual(report["displayed_images"], 3)
        with self.module.open(self.destination) as document:
            self.assertEqual(document[1].get_text(), document[2].get_text())
            self.assertIn("Chapter One", document[2].get_text())

    def test_unsafe_archive_paths_do_not_replace_destination(self):
        for name in ("../escape", "/absolute", "OPS/../escape", "OPS\\escape"):
            with self.subTest(name=name):
                self.write_epub(extra={name: b"unsafe"})
                self.destination.write_bytes(b"keep existing output")
                with self.assertRaisesRegex(SafetyError, "Unsafe EPUB archive path"):
                    self.convert()
                self.assertEqual(self.destination.read_bytes(), b"keep existing output")

    def test_external_css_and_missing_image_are_rejected(self):
        for css in ('@import "https://example.invalid/style.css";',
                    'body { background: url(//example.invalid/picture.png); }',
                    r'body { background: u\72l(https://example.invalid/picture.png); }'):
            with self.subTest(css=css):
                self.write_epub(css=css)
                with self.assertRaisesRegex(SafetyError, "External or unsafe EPUB resource"):
                    self.convert()
                self.assertFalse(self.destination.exists())
        self.write_epub(body='<p>Keep this text.</p><img src="missing.png"/>')
        with self.assertRaisesRegex(SafetyError, "Missing EPUB resource"):
            self.convert()
        self.assertFalse(self.destination.exists())

    def test_css_hidden_source_text_is_not_accepted_as_complete(self):
        self.write_epub(body='<p>Visible text.</p><p style="display:none">Hidden unique content ZQX987.</p>')
        with self.assertRaisesRegex(SafetyError, "source text is missing"):
            self.convert()
        self.assertFalse(self.destination.exists())

    def test_image_extending_outside_page_does_not_replace_output(self):
        self.write_epub(body='<div style="margin-left:-120pt"><img src="picture.png" width="64" height="96"/></div>')
        self.destination.write_bytes(b"keep existing output")
        with self.assertRaisesRegex(SafetyError, "image extends outside the page"):
            self.convert()
        self.assertEqual(self.destination.read_bytes(), b"keep existing output")

    def test_hidden_image_only_spine_chapter_is_rejected(self):
        self.write_epub(body='<div style="display:none"><img src="picture.png" width="64" height="96"/></div>')
        with self.assertRaisesRegex(SafetyError, "chapter 2 has no visible text, images or vector content"):
            self.convert()
        self.assertFalse(self.destination.exists())

    def test_vector_only_spine_chapter_is_preserved(self):
        self.write_epub(body='<div style="width:120pt;height:100pt;background-color:#006699;border:2pt solid black"></div>')
        report = self.convert()
        self.assertEqual(report["chapter_pages"], [1, 1])
        with self.module.open(self.destination) as document:
            self.assertEqual(document[1].get_text().strip(), "")
            self.assertEqual(document[1].get_image_info(), [])
            self.assertTrue(document[1].get_drawings())

    def test_bookdash_groups_keep_illustrations_large_with_their_captions(self):
        second_image = _png(rgb=(153, 80, 32))
        body = ('<div id="wrapper">'
                '<p><img src="story.png" width="300" height="450" alt="First illustration"/></p>'
                '<p>First story caption.</p><p>More first-page story text.</p>'
                '<p><img src="second.png" width="300" height="450" alt="Second illustration"/></p>'
                '<p>Second story caption.</p>'
                '<div class="copyright-text"><p>Original author and illustrator credits.</p>'
                '<p><img class="imprint-logo" src="logo.png" alt="Publisher logo"/></p></div></div>')
        self.write_epub(body=body, chapter_class="chapter", second_image=second_image,
                        extra_images={"story.png": _png(), "logo.png": _png()})
        original = self.source.read_bytes()
        original_mtime = self.source.stat().st_mtime_ns
        second_digest = self.module.Pixmap(second_image).digest
        self.convert()
        with self.module.open(self.destination) as document:
            second_placements = [row for page in document for row in page.get_image_info(hashes=True)
                                 if row["digest"] == second_digest]
            self.assertEqual(len(second_placements), 1)
            self.assertLess(self.module.Rect(second_placements[0]["bbox"]).height, 450)
        report = self.convert(illustration_policy=epub_pdf.BOOKDASH_POLICY)
        first_pdf = self.destination.read_bytes()
        self.assertEqual(report, self.convert(illustration_policy=epub_pdf.BOOKDASH_POLICY))
        self.assertEqual(self.destination.read_bytes(), first_pdf)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.source.stat().st_mtime_ns, original_mtime)
        self.assertEqual(report["spine_count"], 2)
        self.assertEqual(report["chapter_pages"], [1, 3])
        self.assertEqual(report["displayed_images"], 4)
        with self.module.open(self.destination) as document:
            self.assertEqual(len(document), 4)  # Cover, two illustrated story pages, credits.
            expected_text = ("First story caption.", "More first-page story text.",
                             "Second story caption.", "Original author and illustrator credits.")
            text = unicodedata.normalize("NFKC", "\n".join(page.get_text() for page in document))
            for phrase in expected_text:
                self.assertEqual(text.count(phrase), 1)
            self.assertEqual([text.index(phrase) for phrase in expected_text],
                             sorted(text.index(phrase) for phrase in expected_text))
            for page_number, phrase in ((1, expected_text[0]), (2, expected_text[2])):
                page = document[page_number]
                self.assertIn(phrase, page.get_text())
                images = page.get_image_info(hashes=True)
                self.assertEqual(len(images), 1)
                bounds = self.module.Rect(images[0]["bbox"])
                self.assertAlmostEqual(bounds.width, 300, places=2)
                self.assertAlmostEqual(bounds.height, 450, places=2)
            self.assertIn(expected_text[3], document[3].get_text())
            logo = self.module.Rect(document[3].get_image_info()[0]["bbox"])
            self.assertAlmostEqual(logo.width, 48, places=2)
            self.assertAlmostEqual(logo.height, 72, places=2)
            actual_images = Counter((row["width"], row["height"], row["digest"])
                                    for page in document for row in page.get_image_info(hashes=True))
            self.assertEqual(actual_images, Counter({(80, 120, self.module.Pixmap(_png()).digest): 3,
                                                    (80, 120, second_digest): 1}))

    def test_bookdash_policy_rejects_unrecognized_story_structure(self):
        valid_story = ('<p><img src="picture.png" width="300" height="450"/></p><p>Story text.</p>'
                       '<div class="copyright-text"><p>Original credits.</p></div>')
        for body, body_class in ((f'<div id="wrapper">{valid_story}</div>', ""),
                                 (valid_story, "chapter"),
                                 ('<div id="wrapper"><p>There are no illustrations.</p></div>', "chapter")):
            with self.subTest(body=body, body_class=body_class):
                self.write_epub(body=body, chapter_class=body_class)
                self.destination.write_bytes(b"keep existing output")
                with self.assertRaises(SafetyError):
                    self.convert(illustration_policy=epub_pdf.BOOKDASH_POLICY)
                self.assertEqual(self.destination.read_bytes(), b"keep existing output")

    def test_unknown_illustration_policy_and_active_scripts_are_rejected(self):
        with self.assertRaises(SafetyError):
            self.convert(illustration_policy="unreviewed-layout")
        self.assertFalse(self.destination.exists())
        self.write_epub(body='<p>Visible source text.</p><script>document.body.remove();</script>')
        with self.assertRaisesRegex(SafetyError, "active|script"):
            self.convert()
        self.assertFalse(self.destination.exists())

    def test_fixed_print_css_wraps_preformatted_text_instead_of_clipping(self):
        text = "alpha beta gamma delta 123 " * 90
        self.write_epub(body="<pre>" + escape(text) + "</pre>")
        with self.assertRaisesRegex(SafetyError, "outside the page"):
            self.convert()
        self.assertFalse(self.destination.exists())
        report = self.convert(print_css=epub_pdf.PRINT_CSS)
        self.assertGreater(report["chapter_pages"][1], 1)
        self.assertGreater(report["text_characters"], 1500)

    def test_unallowed_renderer_diagnostics_prevent_publication(self):
        with self.assertRaisesRegex(SafetyError, "unknown epub version: 3.0"):
            self.convert(allowed_warnings=[])
        self.assertFalse(self.destination.exists())

    def test_source_cannot_be_replaced_and_source_pin_is_enforced(self):
        original = self.source.read_bytes()
        with self.assertRaisesRegex(SafetyError, "cannot be overwritten"):
            epub_pdf.convert(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), original)
        self.assets["original"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(SafetyError, "source hash/size mismatch"):
            epub_pdf.render(self.recipe, {"original": self.source}, self.assets, self.root / "outputs")
        self.assertFalse((self.root / "outputs").exists())

    def test_render_uses_catalog_destination_and_rejects_escape(self):
        folder = self.root / "outputs"
        result = epub_pdf.render(self.recipe, {"original": self.source}, self.assets, folder)
        self.assertEqual(result, {"book": folder / "REFERENCE/book.pdf"})
        self.assertTrue(result["book"].is_file())
        self.assets["book"]["destination"] = "../escape.pdf"
        with self.assertRaises(SafetyError):
            epub_pdf.render(self.recipe, {"original": self.source}, self.assets, folder)
        self.assertFalse((self.root / "escape.pdf").exists())

    def test_runtime_publishes_only_matching_pinned_pdf(self):
        report = self.convert()
        self.assets["book"].update(size_bytes=report["size_bytes"], sha256=report["sha256"])
        target = self.root / "library"
        source = target / self.assets["original"]["destination"]
        source.parent.mkdir(parents=True)
        source.write_bytes(self.source.read_bytes())
        destination = target / self.assets["book"]["destination"]
        generator = Generator(target, list(self.assets.values()), {self.recipe["id"]: self.recipe}, progress=lambda _: None)
        self.assertEqual(generator.materialize(self.assets["book"], destination), report["sha256"])
        self.assertEqual(destination.read_bytes(), self.destination.read_bytes())
        self.assertEqual(source.read_bytes(), self.source.read_bytes())
        original_digest = recipe_digest(self.recipe, self.assets)
        changed = deepcopy(self.assets)
        changed["original"]["sha256"] = "0" * 64
        self.assertNotEqual(original_digest, recipe_digest(self.recipe, changed))
        self.assets["book"]["sha256"] = "0" * 64
        bad_target = self.root / "bad-library"
        bad_source = bad_target / self.assets["original"]["destination"]
        bad_source.parent.mkdir(parents=True)
        bad_source.write_bytes(self.source.read_bytes())
        bad_destination = bad_target / self.assets["book"]["destination"]
        generator = Generator(bad_target, list(self.assets.values()), {self.recipe["id"]: self.recipe}, progress=lambda _: None)
        with self.assertRaisesRegex(SafetyError, "Generated output SHA-256/size mismatch"):
            generator.materialize(self.assets["book"], bad_destination)
        self.assertFalse(bad_destination.exists())


if __name__ == "__main__":
    unittest.main()
