"""A discovered full-book identity is not a verified or purchased edition."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("hesperian_fallback", Path(__file__).resolve().parents[1] / "scripts/discover_hesperian_fallback.py")
fallback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fallback)


class HesperianFallbackTests(unittest.TestCase):
    def row(self, year=2013, suffix="full", prefix="en"):
        return {"id": year, "source_url": f"https://hesperian.org/wp-content/uploads/pdf/{prefix}_midw_{year}/{prefix}_midw_{year}_{suffix}.pdf",
                "mime_type": "application/pdf", "title": {"rendered": "Full Book Download"}}

    def test_only_complete_english_official_edition_and_duplicates(self):
        rows = [self.row(), self.row(), self.row(2011, "Full_Book"), self.row(2026, "bm"), self.row(2024, prefix="ht")]
        editions = fallback.public_editions(rows)
        self.assertEqual([row["edition"] for row in editions], ["2013", "2011"])
        self.assertFalse(editions[0]["body_verified"])
        with self.assertRaisesRegex(ValueError, "pagination"):
            fallback.public_editions([self.row()] * 100)

    def test_mismatched_path_year_or_external_source_rejected(self):
        row = self.row()
        row["source_url"] = row["source_url"].replace("/en_midw_2013/", "/en_midw_2011/")
        self.assertEqual(fallback.public_editions([row]), [])
        row = self.row()
        row["source_url"] = row["source_url"].replace("hesperian.org", "example.org")
        self.assertEqual(fallback.public_editions([row]), [])

    def test_product_metadata_does_not_supply_download_pin(self):
        recipe = {"product_id": 1, "title": "Book", "current_edition": "2026", "product_page": "https://store.hesperian.org/products/book"}
        variant = {"id": 2, "sku": "PDF", "option1": "English", "option2": "PDF", "requires_shipping": False, "price": 795, "available": True}
        product = {"id": 1, "title": "Book", "variants": [variant]}
        page = '<span data-custom-variant-id="variant_edition">Revised (2026)</span><span data-custom-variant-id="variant_page_count">527</span>'
        result = fallback.purchase_edition(product, page, recipe)
        self.assertIsNone(result["source_url"])
        self.assertIsNone(result["sha256"])
        self.assertFalse(result["content_ready"])
        self.assertEqual(result["price_minor_units"], 795)
        product["variants"].append(dict(variant))
        with self.assertRaisesRegex(ValueError, "one ordinary"):
            fallback.purchase_edition(product, page, recipe)
        product["variants"].pop()
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            fallback.purchase_edition(product, page.replace("2026", "2027"), recipe)


if __name__ == "__main__":
    unittest.main()
