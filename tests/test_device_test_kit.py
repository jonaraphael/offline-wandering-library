import json
from pathlib import Path
import tempfile
import unittest


class DeviceTestKitTests(unittest.TestCase):
    def test_kit_embeds_the_reader_and_weather_vane_search(self):
        try:
            from scripts.build_device_test_kit import create_fixtures
        except ModuleNotFoundError as error:
            if error.name == "libzim":
                self.skipTest("libzim is required for device fixtures")
            raise
        with tempfile.TemporaryDirectory() as directory:
            drive = Path(directory)
            create_fixtures(drive)
            start = (drive / "START_HERE.html").read_text(encoding="utf-8")
            self.assertIn('id="reader-view"', start)
            self.assertIn("split-test.zimaa", start)
            self.assertIn("ZIM ›", start)
            library = drive / "LIBRARY"
            search = (library / "SEARCH.html").read_text(encoding="utf-8")
            self.assertIn("START_HERE.html#/search", search)
            self.assertEqual(len(list(library.glob("INDEX/*/rank.js"))), 1)
            self.assertEqual(len(list(library.glob("INDEX/*/shards.js"))), 1)
            contents = json.loads((library / "INVENTORY.json").read_bytes())
            self.assertIn("weather vane", contents["assets"][0]["description"])
