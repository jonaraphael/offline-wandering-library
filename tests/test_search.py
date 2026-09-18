"""Cross-language index tests use tiny local fixtures, never network data."""
from __future__ import annotations

import importlib.util
import io
import json
import logging
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch
import zipfile

from owl.search import HEADER_SIZE, SearchError, build_search, check_extractors, tokens
from owl.safety import SafetyError


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name).resolve()
        self.assets = []

    def add(self, name, text, **metadata):
        path = self.target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        asset = {"id": path.stem, "title": path.stem, "destination": name,
                 "category": "reference", "format": path.suffix[1:], **metadata}
        self.assets.append(asset)
        return asset

    def read_index(self):
        data = (self.target / "SEARCH/library.owl").read_bytes()
        self.assertEqual(data[:8], b"OWLIDX2\n")
        header = json.loads(data[12:12 + struct.unpack_from("<I", data, 8)[0]])
        self.assertEqual(header["size"], len(data))
        def record(table, index):
            start, length = struct.unpack_from("<QI", data, table + index * 12)
            return json.loads(data[start:start + length])
        docs = [record(header["docs_offset"], n) for n in range(header["documents"])]
        terms = [record(header["lexicon_offset"], n) for n in range(header["terms"])]
        return data, header, docs, terms

    def run_js(self, body, prelude=""):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for the browser engine test")
        page = (self.target / "SEARCH.html").read_text(encoding="utf-8")
        script = re.search(r"<script>([\s\S]*?)</script>", page).group(1)
        engine = self.target / "engine.cjs"
        engine.write_text(script, encoding="utf-8", newline="\n")
        driver = self.target / "driver.cjs"
        driver.write_text("const fs = require('node:fs');\n" + prelude + "\nconst engine = require('./engine.cjs');\n"
                          "(async () => { const bytes = fs.readFileSync('SEARCH/library.owl');\n"
                          "let maxRead = 0, totalRead = 0;\n"
                          "const blob = new Blob([bytes]);\n"
                          "const file = {size:blob.size, slice(a,b) { maxRead=Math.max(maxRead,b-a); totalRead+=b-a; return blob.slice(a,b); }};\n"
                          "const index = new engine.Index(file); await index.open();\n" + body +
                          "\n})().catch(e => {console.error(e); process.exit(1)});\n",
                          encoding="utf-8", newline="\n")
        result = subprocess.run([node, str(driver)], cwd=self.target,
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_complete_text_passages_metadata_and_determinism(self):
        body = "water sanitation " * 5000 + "finalraretoken"
        self.add("CRITICAL/WATER/guide.html", "<html><script>secret_script</script><h1>Handwashing</h1><p>" + body + "</p></html>",
                 title="Drinking water", critical=True, tags=["hygiene"], publisher="Trusted source")
        report = build_search(self.target, self.assets)
        data, header, docs, terms = self.read_index()
        lexicon = {entry[0] for entry in terms}
        self.assertGreater(len(docs), 5)
        self.assertIn("finalraretoken", lexicon)
        self.assertIn("handwashing", lexicon)
        self.assertIn("hygiene", lexicon)
        self.assertIn("trusted", lexicon)
        self.assertNotIn("secret", lexicon)
        self.assertTrue(all(len(doc["text"]) <= 8192 for doc in docs))
        self.assertEqual(report["assets"][0]["status"], "full_text")
        self.assertEqual(report["generated_files"], ["SEARCH.html", "SEARCH/library.owl", "SEARCH/coverage.json"])
        build_search(self.target, self.assets)
        self.assertEqual((self.target / "SEARCH/library.owl").read_bytes(), data)
        self.assertFalse(list((self.target / "SEARCH").glob("owl-index-*")))

    def test_browser_engine_ranking_snippets_unicode_and_safe_links(self):
        self.add("BOOKS/water.txt", "boiling clean water reduces microbial hazards", title="Water purification", category="water")
        self.add("BOOKS/other.txt", "A mechanical textbook mentions water only once. café 𐐀", title="Machines")
        build_search(self.target, self.assets)
        result = self.run_js("""
          const found = await index.search('water purification');
          const unicode = await index.search('CAFÉ 𐐨');
          console.log(JSON.stringify({found, unicode, maxRead,
            bad: engine.safeLink({destination:'../outside.html'}),
            good: engine.safeLink({destination:'BOOKS/a #b.pdf',format:'pdf',page:3})}));
        """)
        self.assertEqual(result["found"]["results"][0]["title"], "Water purification")
        self.assertIn("boiling", result["found"]["results"][0]["snippet"])
        self.assertEqual(result["unicode"]["results"][0]["title"], "Machines")
        self.assertEqual(result["unicode"]["words"], ["café", "𐐨"])
        self.assertIn("café 𐐀", result["unicode"]["results"][0]["text"])
        self.assertLessEqual(result["maxRead"], 1024 * 1024)
        self.assertIsNone(result["bad"])
        self.assertEqual(result["good"], "BOOKS/a%20%23b.pdf#page=3")

    def test_browser_streams_high_frequency_postings_and_retains_top_k(self):
        # Over 4096 passages forces multiple bounded posting-block reads.
        self.add("BOOKS/large.txt", ("common " + "x" * 8184 + "\n") * 4300 + "common uncommonwinningterm", title="Common")
        build_search(self.target, self.assets)
        result = self.run_js("""
          const found = await index.search('common uncommonwinningterm', {limit:7});
          console.log(JSON.stringify({count:found.results.length, scanned:found.scanned,
            best:found.results[0].text, maxRead}));
        """)
        self.assertEqual(result["count"], 7)
        self.assertGreater(result["scanned"], 4096)
        self.assertIn("uncommonwinningterm", result["best"])
        self.assertLessEqual(result["maxRead"], 49152)

    def test_learning_filters_rank_all_eligible_candidates_and_overlap(self):
        for n in range(70):
            self.add(f"REFERENCE/high-{n:02}.txt", "hydration", title="Hydration")
        self.add("BOOKS/textbook.txt", "hydration " + "background " * 200,
                 title="Study volume", resource_type="textbook", illustrated=True)
        self.add("BOOKS/plain.txt", "hydration " + "background " * 100,
                 title="Plain volume", resource_type="textbook")
        self.add("CRITICAL/guide.txt", "hydration " + "background " * 150,
                 title="Practical guide", resource_type="guide", illustrated=True)
        for path in ("ZIM/OTHER/spoof.txt", "SOFTWARE/spoof.txt"):
            self.add(path, "hydration", title="Hydration", resource_type="textbook", illustrated=True)
        self.add("REFERENCE/special.txt", "hydration", title="Hydration",
                 resource_type="textbook", illustrated=True, reader_required=True)
        report = build_search(self.target, self.assets)
        self.assertEqual(report["format_version"], 2)
        data, header, docs, _ = self.read_index()
        self.assertEqual(header["flags_offset"], header["docs_offset"] + len(docs) * 12)
        flags = {doc["destination"]: data[header["flags_offset"] + i] for i, doc in enumerate(docs)}
        self.assertEqual(flags["BOOKS/textbook.txt"], 3)
        self.assertEqual(flags["BOOKS/plain.txt"], 1)
        self.assertEqual(flags["CRITICAL/guide.txt"], 2)
        self.assertEqual(flags["ZIM/OTHER/spoof.txt"], 0)
        self.assertEqual(flags["SOFTWARE/spoof.txt"], 0)
        result = self.run_js("""
          let recordReads = 0;
          const record = index.record.bind(index);
          index.record = async (table, id) => { if (table === index.header.docs_offset) recordReads++; return record(table, id); };
          const all = await index.search('hydration');
          recordReads = 0;
          const textbooks = await index.search('hydration', {shelf:'textbooks'});
          const textbookRecordReads = recordReads;
          const illustrated = await index.search('hydration', {shelf:'illustrated-guides'});
          const byLabel = await index.search('textbook', {shelf:'textbooks'});
          console.log(JSON.stringify({all, textbooks, illustrated, byLabel, textbookRecordReads, maxRead}));
        """)
        self.assertEqual(len(result["all"]["results"]), 50)
        self.assertFalse(any(doc["destination"].startswith("BOOKS/") for doc in result["all"]["results"]))
        self.assertEqual([doc["title"] for doc in result["textbooks"]["results"]], ["Plain volume", "Study volume"])
        self.assertEqual({doc["title"] for doc in result["illustrated"]["results"]}, {"Practical guide", "Study volume"})
        self.assertEqual(result["textbooks"]["matches"], 2)
        self.assertEqual(result["textbookRecordReads"], 2)
        self.assertEqual(result["byLabel"]["matches"], 2)
        self.assertLessEqual(result["maxRead"], 65536)

    def test_filter_flag_pages_use_bounded_reads_across_sparse_candidates(self):
        # A sparse synthetic index exercises >64KiB of passage flags without a
        # large source corpus. Only two passage IDs have the searched term.
        self.add("textbook.txt", "water", resource_type="textbook")
        build_search(self.target, self.assets)
        _, _, docs, _ = self.read_index()
        document = json.dumps(docs[0]).encode("utf-8")
        count = 65540
        data = bytearray(HEADER_SIZE) + document
        docs_offset = len(data)
        data.extend(struct.pack("<QI", HEADER_SIZE, len(document)) * count)
        flags_offset = len(data)
        data.extend(b"\x00" * count)
        data[flags_offset] = data[flags_offset + count - 1] = 1
        postings_offset = len(data)
        data.extend(struct.pack("<III", 0, 1, 1) + struct.pack("<III", count - 1, 1, 1))
        term = json.dumps(["water", postings_offset, 2]).encode("utf-8")
        term_offset = len(data)
        data.extend(term)
        lexicon_offset = len(data)
        data.extend(struct.pack("<QI", term_offset, len(term)))
        header = json.dumps({"version": 2, "documents": count, "terms": 1, "average_length": 1,
                             "docs_offset": docs_offset, "flags_offset": flags_offset,
                             "lexicon_offset": lexicon_offset, "size": len(data),
                             "tokenizer": "NFKC-lower-unicode-letter-number-v1"}).encode("utf-8")
        data[:12 + len(header)] = b"OWLIDX2\n" + struct.pack("<I", len(header)) + header
        (self.target / "SEARCH/library.owl").write_bytes(data)
        result = self.run_js("""
          const blocks = [];
          const read = index.read.bind(index);
          index.read = async (at, length) => { if (at >= index.header.flags_offset && at < index.header.flags_offset + index.header.documents) blocks.push(length); return read(at, length); };
          const found = await index.search('water', {shelf:'textbooks'});
          console.log(JSON.stringify({ids:found.results.map(row=>row.id), blocks, maxRead}));
        """)
        self.assertEqual(result["ids"], [0, count - 1])
        self.assertEqual(result["blocks"], [65536, 4])
        self.assertLessEqual(result["maxRead"], 65536)

    def test_attribution_and_illustration_labels_survive_real_result_rendering(self):
        attribution = "Access for free at openstax.org. <b>Publisher credit</b>"
        license_name = "CC-BY-NC-SA-4.0"
        self.add("BOOKS/biology.txt", "Photosynthesis converts sunlight into chemical energy.",
                 title="Biology", resource_type="textbook", illustrated=True,
                 attribution=attribution, license=license_name)
        build_search(self.target, self.assets)
        document = self.read_index()[2][0]
        self.assertEqual(document["attribution"], attribution)
        self.assertEqual(document["license"], license_name)
        prelude = """
          const ui = {};
          function element(tag) { return {tag, textContent:'', children:[], handlers:{}, value:'',
            addEventListener(event, handler){this.handlers[event]=handler}, focus(){},
            append(...children){this.children.push(...children)}, replaceChildren(...children){this.children=children},
            set innerHTML(value){throw new Error('Unsafe HTML rendering')} }; }
          global.document = {getElementById(id){return ui[id] || (ui[id]=element(id))}, createElement:element};
        """
        result = self.run_js("""
          const found = await index.search('photosynthesis', {shelf:'textbooks'});
          await ui.indexFile.handlers.change({target:{files:[file]}});
          ui.query.value = 'photosynthesis'; ui.shelf.value = 'textbooks';
          await ui.searchForm.handlers.submit({preventDefault(){}});
          console.log(JSON.stringify({record:found.results[0], labels:engine.resourceLabels(found.results[0]),
            rendered:ui.results.children[0].children.map(node=>({tag:node.tag,text:node.textContent})), status:ui.status.textContent}));
        """, prelude=prelude)
        self.assertEqual(result["record"]["attribution"], attribution)
        self.assertEqual(result["labels"], ["Textbook", "Illustrated"])
        notice = [node for node in result["rendered"] if attribution in node["text"]]
        self.assertEqual(len(notice), 1)
        self.assertEqual(notice[0]["tag"], "p")
        self.assertIn("License: " + license_name, notice[0]["text"])
        self.assertIn("1 matches", result["status"])

    def test_metadata_only_is_explicit(self):
        self.add("SOFTWARE/reader.bin", "binary", format="exe", title="Reader", description="Offline reader")
        report = build_search(self.target, self.assets)
        self.assertEqual(report["assets"][0]["status"], "metadata_only")
        self.assertTrue(report["warnings"])
        self.assertTrue(self.read_index()[2][0]["metadata_only"])

    def test_epub_extracts_all_text_members_without_writing_archive_paths(self):
        path = self.target / "book.epub"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("OEBPS/chapter.xhtml", "<h1>Agriculture</h1><p>compost nutrients</p>")
            archive.writestr("../../outside.txt", "unusualarchivetoken")
        report = build_search(self.target, [{"destination": "book.epub", "format": "epub", "title": "Growing"}])
        self.assertEqual(report["documents"], 2)
        self.assertIn("unusualarchivetoken", [term[0] for term in self.read_index()[3]])
        self.assertFalse((self.target.parent / "outside.txt").exists())

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf not installed")
    def test_pdf_extracts_text_and_reports_empty_scan_pages(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 40 750 Td (emergencybandage) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(content)
        writer.add_blank_page(width=612, height=792)
        writer.write(self.target / "aid.pdf")
        report = build_search(self.target, [{"destination": "aid.pdf", "format": "pdf", "title": "First aid"}])
        self.assertEqual(report["assets"][0]["status"], "partial")
        self.assertEqual(report["assets"][0]["empty_units"], 1)
        self.assertIn("emergencybandage", [term[0] for term in self.read_index()[3]])
        self.assertEqual(self.read_index()[2][0]["page"], 1)

    @unittest.skipUnless(importlib.util.find_spec("libzim"), "libzim optional extra not installed")
    def test_zim_real_archive_extracts_article_body(self):
        from libzim.writer import Creator, Item, StringProvider, Hint
        class Article(Item):
            def get_path(self): return "water"
            def get_title(self): return "Water safety"
            def get_mimetype(self): return "text/html"
            def get_contentprovider(self): return StringProvider("<h1>Safe water</h1><p>archivebodyuniqueterm</p>")
            def get_hints(self): return {Hint.FRONT_ARTICLE: True}
        with Creator(self.target / "sample.zim") as creator:
            creator.add_item(Article())
            creator.set_mainpath("water")
        report = build_search(self.target, [{"destination": "sample.zim", "format": "zim", "title": "Reference",
                                            "resource_type": "textbook", "illustrated": True, "reader_required": False}])
        self.assertIn("archivebodyuniqueterm", [term[0] for term in self.read_index()[3]])
        self.assertEqual(self.read_index()[2][0]["entry"], "water")
        self.assertTrue(self.read_index()[2][0]["reader_required"])
        self.assertEqual(report["assets"][0]["status"], "full_text")
        result = self.run_js("""
          const all = await index.search('archivebodyuniqueterm');
          const textbooks = await index.search('archivebodyuniqueterm', {shelf:'textbooks'});
          const illustrated = await index.search('archivebodyuniqueterm', {shelf:'illustrated-guides'});
          console.log(JSON.stringify({all:all.matches, textbooks:textbooks.matches, illustrated:illustrated.matches}));
        """)
        self.assertEqual(result, {"all": 1, "textbooks": 0, "illustrated": 0})

    def test_invalid_collection_flags_are_rejected(self):
        self.add("book.txt", "water", resource_type="textbook")
        build_search(self.target, self.assets)
        raw, header, _, _ = self.read_index()
        data = bytearray(raw)
        data[header["flags_offset"]] = 128
        (self.target / "SEARCH/library.owl").write_bytes(data)
        result = self.run_js("""
          let error = '';
          try { await index.search('water', {shelf:'textbooks'}); }
          catch (e) { error = e.message; }
          console.log(JSON.stringify({error}));
        """)
        self.assertIn("Invalid resource flags", result["error"])

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf not installed")
    def test_pdf_warning_flood_is_bounded_partial_and_logging_restored(self):
        self.add("reference.pdf", "fixture for mocked PDF decoder")
        logger = logging.getLogger("pypdf")
        before = (logger.handlers[:], logger.level, logger.propagate)
        class Page:
            def extract_text(self):
                for _ in range(2500):
                    logging.getLogger("pypdf._cmap").warning("Unknown font encoding: %s", "X" * 5000)
                return "This extracted text has an uncertain font mapping."
        class Reader:
            is_encrypted = False
            pages = [Page()]
        stderr = io.StringIO()
        messages = []
        with patch("pypdf.PdfReader", return_value=Reader()), redirect_stderr(stderr):
            report = build_search(self.target, self.assets, progress=messages.append)
        self.assertEqual(stderr.getvalue(), "")
        coverage = report["assets"][0]
        self.assertEqual(coverage["status"], "partial")
        self.assertEqual(coverage["warning_count"], 2500)
        self.assertEqual(len(coverage["warnings"]), 20)
        self.assertTrue(all(len(message) <= 2049 for message in coverage["warnings"]))
        self.assertIn("Unknown font encoding", coverage["warnings"][0])
        self.assertEqual((logger.handlers, logger.level, logger.propagate), before)
        self.assertTrue(any(message.startswith("INDEX 1/1 reference.pdf") for message in messages))
        self.assertTrue(any("2,500 notices" in message for message in messages))
        self.assertTrue(messages[-1].startswith("INDEX COMPLETE:"))

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf not installed")
    def test_pdf_failure_restores_logging_and_retains_previous_index(self):
        self.add("reference.txt", "original indexed content")
        build_search(self.target, self.assets)
        original = (self.target / "SEARCH/library.owl").read_bytes()
        asset = self.add("corrupt.pdf", "corrupt fixture")
        logger = logging.getLogger("pypdf")
        before = (logger.handlers[:], logger.level, logger.propagate)
        with patch("pypdf.PdfReader", side_effect=ValueError("corrupt PDF")):
            with self.assertRaisesRegex(ValueError, "corrupt PDF"):
                build_search(self.target, [asset])
        self.assertEqual((logger.handlers, logger.level, logger.propagate), before)
        self.assertEqual((self.target / "SEARCH/library.owl").read_bytes(), original)

    def test_progress_interval_is_throttled_during_large_assets(self):
        self.add("large.txt", ("water " + "x" * 8185 + "\n") * 2200)
        messages = []
        # Constant monotonic time means periodic progress stays suppressed, while
        # asset and stage boundaries still report useful progress.
        with patch("owl.search.time.monotonic", return_value=10):
            build_search(self.target, self.assets, progress=messages.append)
        self.assertFalse(any("total;" in message for message in messages))
        messages.clear()
        with patch("owl.search.time.monotonic", side_effect=lambda: len(messages) * 10 + 20):
            build_search(self.target, self.assets, progress=messages.append)
        self.assertTrue(any("total;" in message for message in messages))

    def test_missing_extractor_fails_before_writing(self):
        with patch("owl.search.importlib.util.find_spec", return_value=None):
            with self.assertRaisesRegex(SearchError, "libzim"):
                build_search(self.target, [{"destination": "a.zim", "format": "zim"}])
        self.assertFalse((self.target / "SEARCH").exists())

    def test_unsafe_or_symlink_destinations_rejected(self):
        with self.assertRaises(SafetyError):
            build_search(self.target, [{"destination": "../secret.txt", "format": "txt"}])
        (self.target / "link.txt").symlink_to(self.target / "missing")
        with self.assertRaises(SafetyError):
            build_search(self.target, [{"destination": "link.txt", "format": "txt"}])

    def test_truncated_index_rejected_in_browser(self):
        self.add("plain.txt", "useful")
        build_search(self.target, self.assets)
        result = self.run_js("""
          let error = '';
          try { await new engine.Index(blob.slice(0, blob.size - 1)).open(); }
          catch (e) { error = e.message; }
          console.log(JSON.stringify({error}));
        """)
        self.assertIn("truncated", result["error"])


if __name__ == "__main__":
    unittest.main()
