import contextlib
import importlib.util
import io
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_story_ladder", ROOT / "scripts/build_story_ladder.py")
ladder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ladder)


class StoryLadderTest(unittest.TestCase):
    def test_pdfs_manifest_and_catalog_agree(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status = ladder.check()
        self.assertEqual(status, 0, errors.getvalue())

    def test_every_preset_carries_every_age(self):
        books = ladder.books()
        self.assertEqual([book["age"] for book in books], list(range(1, 19)))
        for path in sorted((ROOT / "profiles").glob("*.yaml")):
            profile = yaml.safe_load(path.read_text(encoding="utf-8"))
            if "default_resources" in profile:
                with self.subTest(profile=path.stem):
                    self.assertIn(ladder.RESOURCE, profile["default_resources"])

    def test_capacity_core_keeps_the_whole_ladder(self):
        order = yaml.safe_load((ROOT / "catalog/capacity-order.yaml").read_text(encoding="utf-8"))
        self.assertEqual(order["core"]["culture"], [book["id"] for book in ladder.books()])


if __name__ == "__main__":
    unittest.main()
