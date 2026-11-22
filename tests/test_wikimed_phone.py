import unittest

from pypdf import PdfReader

from owl.wikimed_phone import BUDGET, DESTINATION, ROOT, manifest, verified_volume, volumes


class WikiMedPhoneTest(unittest.TestCase):
    def test_source_edition_gates_all_volumes(self):
        bundle = manifest()
        self.assertEqual(volumes([], bundle), [])
        self.assertEqual(volumes([{"id": bundle["source_id"], "sha256": "0" * 64}], bundle), [])
        source = {"id": bundle["source_id"], "sha256": bundle["source_sha256"]}
        self.assertEqual(len(volumes([source], bundle)), 12)
        self.assertTrue(DESTINATION.startswith("CRITICAL/MEDICAL/"))
        self.assertLess(sum(volume["bytes"] for volume in bundle["volumes"]), BUDGET)
        paths = [row["path"] for volume in bundle["volumes"] for row in volume["articles"]]
        self.assertGreaterEqual(len(paths), 1000)
        self.assertLessEqual(len(paths), 2000)
        self.assertEqual(len(paths), len(set(paths)))

    def test_volume_pins_outline_internal_links_and_selectable_text(self):
        for entry in manifest()["volumes"]:
            with self.subTest(volume=entry["file"]):
                verified_volume(entry)
                pdf = PdfReader(ROOT / entry["file"])
                self.assertEqual([heading.title for heading in pdf.outline],
                                 [article["title"] for article in entry["articles"]])
                first_article = pdf.get_destination_page_number(pdf.outline[0])
                links = [ref.get_object() for page in pdf.pages[:first_article] for ref in page["/Annots"]]
                self.assertEqual(len(links), len(entry["articles"]))
                self.assertTrue(all(link.get("/Dest") for link in links))
                self.assertIn("Wikipedia contributors", pdf.pages[first_article].extract_text())
                for destination, article in zip(pdf.outline, entry["articles"], strict=True):
                    page = pdf.pages[pdf.get_destination_page_number(destination)]
                    uris = [action.get("/URI") for ref in page["/Annots"]
                            if (action := ref.get_object().get("/A"))]
                    self.assertIn(article["revision"], uris)
