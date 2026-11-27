import unittest

from owl.phone_terms import TERMS_FILE, compile_terms, encode_terms, load_terms
from owl.search_shards import load_manifest


class PhoneTermsTests(unittest.TestCase):
    def test_committed_words_match_the_search_shards(self):
        # After changing catalog/search, run scripts/build_phone_terms.py.
        self.assertEqual(TERMS_FILE.read_bytes(), encode_terms(compile_terms()))

    def test_words_name_what_a_first_aid_chapter_covers(self):
        sources = load_manifest()["sources"]
        chapter = next(digest for digest, shard in sources.items() if shard["asset_id"] == "hesperian_en_wtnd_2025_10")
        words = load_terms()[chapter]
        self.assertLessEqual(len(words), 16)
        self.assertTrue({"bandage", "wound", "splint"} <= set(words), words)
        self.assertTrue(all(word.isalpha() and word == word.lower() for word in words))


if __name__ == "__main__":
    unittest.main()
