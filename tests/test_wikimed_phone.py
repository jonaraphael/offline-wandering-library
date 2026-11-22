import unittest

from pypdf import PdfReader

from owl.wikimed_phone import DESTINATION, ROOT, manifest, verified_volume, volumes


class WikiMedPhoneTest(unittest.TestCase):
    def test_source_edition_gates_all_four_volumes(self):
        bundle = manifest()
        self.assertEqual(volumes([], bundle), [])
        self.assertEqual(volumes([{"id": bundle["source_id"], "sha256": "0" * 64}], bundle), [])
        source = {"id": bundle["source_id"], "sha256": bundle["source_sha256"]}
        self.assertEqual(len(volumes([source], bundle)), 4)
        self.assertTrue(DESTINATION.startswith("CRITICAL/MEDICAL/"))

    def test_volume_pins_outline_internal_links_and_selectable_text(self):
        for entry in manifest()["volumes"]:
            with self.subTest(volume=entry["file"]):
                verified_volume(entry)
                pdf = PdfReader(ROOT / entry["file"])
                self.assertEqual([heading.title for heading in pdf.outline],
                                 [article["title"] for article in entry["articles"]])
                links = [ref.get_object() for ref in pdf.pages[0]["/Annots"]]
                self.assertEqual(len(links), len(entry["articles"]))
                self.assertTrue(all(link.get("/Dest") for link in links))
                self.assertIn("Wikipedia contributors", pdf.pages[1].extract_text())
