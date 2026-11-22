from pathlib import Path
import re
import tomllib
import unittest

import yaml

from owl import __version__
from owl.catalog import load_catalog
from owl.navigation import reader_payload


ROOT = Path(__file__).resolve().parents[1]


class OperationsTests(unittest.TestCase):
    def test_pages_deploy_waits_for_same_workflows_test_jobs(self):
        workflows = ROOT / ".github/workflows"
        tests = yaml.load((workflows / "test.yml").read_text(), Loader=yaml.BaseLoader)
        pages = yaml.load((workflows / "pages.yml").read_text(), Loader=yaml.BaseLoader)
        publish = tests["jobs"]["publish"]
        self.assertIn("workflow_dispatch", tests["on"])
        self.assertEqual(set(pages["on"]), {"workflow_call"})
        self.assertEqual(set(publish["needs"]), set(tests["jobs"]) - {"publish"})
        self.assertIn("github.ref == 'refs/heads/main'", publish["if"])
        self.assertEqual(publish["uses"], "./.github/workflows/pages.yml")
        runs = "\n".join(step.get("run", "") for step in tests["jobs"]["pages"]["steps"])
        for stem in ("archive-resume-route", "capacity-probe", "diagnostics", "remove-tree"):
            self.assertIn(f"tests/{stem}.test.mjs", runs)

    def test_source_check_workflow_configures_live_routes_and_issue_writes(self):
        path = ROOT / ".github/workflows/check-links.yml"
        check = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(check["permissions"]["issues"], "write")
        probe = next(step for step in check["jobs"]["check-links"]["steps"] if step.get("id") == "probe")
        self.assertIn("--pages-base https://jonaraphael.github.io/offline-wandering-library/", probe["run"])
        self.assertIn("--relay-base", probe["run"])
        self.assertIn("--origin https://jonaraphael.github.io", probe["run"])

    def test_relay_configuration_and_drive_source_notes(self):
        relay = tomllib.loads((ROOT / "relay/wrangler.toml").read_text())
        self.assertTrue(relay["workers_dev"])
        self.assertEqual(relay["name"], "owl-publisher-relay")
        self.assertEqual(relay["vars"], {"ALLOWED_ORIGIN": "https://jonaraphael.github.io"})
        relay_doc = (ROOT / "relay/README.md").read_text(encoding="utf-8")
        for asset in load_catalog(ROOT / "catalog/library.yaml"):
            if not asset["redistributable"]:
                self.assertIn(f"- {asset['publisher']}\n", relay_doc)
        for repository, release in (("desktop", "2.5.1"), ("apple", "3.14.0"), ("android", "3.14.0")):
            self.assertIn(f"https://github.com/kiwix/kiwix-{repository}/tree/{release}", reader_payload([])["readme"])
        package = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(__version__, package["project"]["version"])
        self.assertIn(f"## {__version__}", (ROOT / "CHANGELOG.md").read_text())

    def test_archived_acquisition_notes_are_linked_from_the_docs_index(self):
        docs = ROOT / "docs"
        self.assertIn("(archive/README.md)", (docs / "README.md").read_text(encoding="utf-8"))
        archive = docs / "archive"
        archived = re.findall(r"^\- \[[^]]+\]\(([^)]+)\)$", (archive / "README.md").read_text(encoding="utf-8"), re.M)
        self.assertEqual(set(archived), {path.name for path in archive.iterdir() if path.name != "README.md"})
        self.assertFalse((docs / "acquisition-trial-pause.md").exists())
