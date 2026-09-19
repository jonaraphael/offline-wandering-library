"""Registered representations use actual pinned assets, never compression ratios."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from owl.build import main
from owl.catalog import CatalogError, capacity_plan, resolve_content, resolve_locked_content
from owl.resources import load_resources, resolve_resources


class EditionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.registry_path = self.root / "resources.yaml"
        self.assets = [self.asset("critical", 10, critical=True), self.asset("direct", 30),
                       self.asset("archive", 20, format="zim", destination="ZIM/archive.zim", reader_required=True),
                       self.asset("reader", 2, format="zip", destination="SOFTWARE/reader.zip")]
        self.resource = {"id": "collection", "number": 1, "title": "Collection", "target_bytes": 50,
                         "status": "partial", "reason": "Published scope incomplete", "asset_ids": ["critical", "archive"],
                         "editions": {
                             "direct": {"asset_ids": ["critical", "direct"], "target_bytes": 45, "status": "ready", "reason": ""},
                             "compact": {"asset_ids": ["critical", "archive"], "target_bytes": 15, "status": "ready", "reason": ""}}}
        self.readers = {"id": "archive-readers", "title": "Readers", "target_bytes": 0,
                        "asset_ids": ["reader"], "status": "ready"}
        self.profile = {"id": "test", "default_resources": ["collection"], "readers_budget_bytes": 5,
                        "capacity_bytes": 10**8, "reserve_bytes": 100, "search_budget_bytes": 1_000_000, "index_scratch_budget_bytes": 3_000_000}

    @staticmethod
    def asset(identity, size, **changes):
        return {"id": identity, "size_bytes": size, "sha256": "a" * 64, "status": "resolved", "format": "txt",
                "destination": f"REFERENCE/{identity}.txt", "profiles": [], "required": True,
                "title": identity, "category": "reference", "version": "1", "license": "CC0-1.0",
                "source_url": "https://example.org/source", "redistributable": True, **changes}

    def registry(self):
        self.registry_path.write_text(yaml.safe_dump({"schema_version": 1, "resources": [self.resource, self.readers]}), encoding="utf-8")
        return load_resources(self.registry_path, self.assets)

    def resolve(self, **kwargs):
        return resolve_resources(self.assets, self.profile, self.registry(), **kwargs)

    def test_direct_replaces_assets_target_and_status_without_reader_dependency(self):
        result = self.resolve(editions=["1=direct"])
        self.assertEqual([a["id"] for a in result["assets"]], ["critical", "direct"])
        self.assertEqual(result["explicit_editions"], {"collection": "direct"})
        self.assertEqual(result["readers_budget_bytes"], 0)
        self.assertEqual(result["incomplete_resources"], [])
        row = result["resource_rows"][0]
        self.assertEqual((row["edition"], row["planning_target_bytes"], row["effective_target_bytes"], row["known_bytes"]),
                         ("direct", 45, 45, 40))
        self.assertTrue(result["customized"])

    def test_compact_uses_actual_known_size_and_auto_includes_readers(self):
        result = self.resolve(editions="collection=compact")
        self.assertEqual(result["content_target_bytes"], 30)  # Actual files exceed the 15-byte target.
        self.assertEqual(result["planned_total_bytes"], 35)
        self.assertEqual(result["resolved_asset_bytes"], 32)
        self.assertEqual(result["auto_included_ids"], ["archive-readers"])
        self.assertEqual(result["resource_rows"][1]["edition"], "published")
        with self.assertRaisesRegex(CatalogError, "need archive-readers"):
            self.resolve(editions="1=compact", exclude="archive-readers")

    def test_profile_editions_are_defaults_not_customizations_and_are_locked(self):
        self.profile['default_editions'] = {'collection': 'direct'}
        result = self.resolve()
        self.assertFalse(result['customized'])
        self.assertEqual(result['explicit_editions'], {})
        self.assertEqual(result['effective_editions'], {'collection': 'direct'})
        self.assertEqual({a['id'] for a in result['assets']}, {'critical', 'direct'})
        assets = result.pop('assets')
        # A future change to the live profile must not alter this locked edition.
        self.profile['default_editions']['collection'] = 'compact'
        locked, _, report = resolve_locked_content(assets, self.profile,
            {'profile_id': 'test', 'content_selection': result})
        self.assertEqual({a['id'] for a in locked}, {'critical', 'direct'})
        self.assertEqual(report['effective_editions'], {'collection': 'direct'})
        self.assertEqual(self.resolve(editions='collection=published')['resource_rows'][0]['edition'], 'published')
        excluded = self.resolve(exclude='collection')
        self.assertEqual(excluded['effective_editions'], {})
        self.assertEqual(excluded['assets'], [])

    def test_invalid_profile_editions_fail_before_selection(self):
        for defaults in ([], {'unknown': 'direct'}, {'collection': 'missing'}, {'collection': True}):
            self.profile['default_editions'] = defaults
            with self.subTest(defaults=defaults), self.assertRaises(CatalogError):
                self.resolve()

    def test_published_keeps_profile_target_and_membership_overrides(self):
        self.profile["resource_overrides"] = {"collection": {"target_bytes": 17, "exclude_asset_ids": ["archive"]}}
        published = self.resolve(editions="collection=published")
        self.assertEqual(published["content_target_bytes"], 17)
        self.assertEqual([a["id"] for a in published["assets"]], ["critical"])
        direct = self.resolve(editions="collection=direct")
        self.assertEqual(direct["content_target_bytes"], 45)
        self.assertEqual([a["id"] for a in direct["assets"]], ["critical", "direct"])
        self.profile["resource_overrides"]["collection"]["exclude_asset_ids"] = ["direct"]
        self.assertEqual([a["id"] for a in self.resolve(editions="1=direct")["assets"]], ["critical"])

    def test_selection_syntax_unknown_unavailable_excluded_and_conflicting_editions(self):
        cases = [(["collection=direct", "1=compact"], {}, "conflicting"),
                 (["collection=zip"], {}, "unknown edition"),
                 (["999=direct"], {}, "unknown resource"),
                 (["collection"], {}, "RESOURCE="),
                 (["collection=direct"], {"exclude": "collection"}, "requires a selected resource"),
                 (["archive-readers=direct"], {"include": "archive-readers"}, "unavailable")]
        for editions, changes, expected in cases:
            with self.subTest(editions=editions, changes=changes), self.assertRaisesRegex(CatalogError, expected):
                self.resolve(editions=editions, **changes)
        result = self.resolve(editions=["01=direct,collection=direct"])
        self.assertEqual(result["explicit_editions"], {"collection": "direct"})
        self.profile["default_resources"] = []
        with self.assertRaisesRegex(CatalogError, "requires a selected resource"):
            self.resolve(editions="collection=direct")
        self.assertEqual(self.resolve(include="1", editions="1=direct")["selected_ids"], ["collection"])

    def test_invalid_edition_sources_and_schema_are_rejected(self):
        original = deepcopy(self.resource)
        cases = [({"direct": {**original["editions"]["direct"], "target_bytes": True}}, "integer"),
                 ({"direct": {**original["editions"]["direct"], "asset_ids": ["unknown"]}}, "unknown asset"),
                 ({"direct": {**original["editions"]["direct"], "asset_ids": []}}, "pinned source"),
                 ({"direct": {**original["editions"]["direct"], "asset_ids": ["critical", "archive"]}}, "ordinary readable"),
                 ({"direct": {**original["editions"]["direct"], "asset_ids": ["direct"]}}, "preserve critical"),
                 ({"compact": {**original["editions"]["compact"], "asset_ids": ["critical"]}}, "ZIM"),
                 ({"compact": {**original["editions"]["compact"], "asset_ids": ["archive"]}}, "preserve critical"),
                 ({"direct": {**original["editions"]["direct"], "status": "partial", "reason": ""}}, "nonempty reason"),
                 ({"published": original["editions"]["direct"]}, "only direct and compact")]
        for editions, error in cases:
            self.resource = {**original, "editions": editions}
            with self.subTest(editions=editions), self.assertRaisesRegex(CatalogError, error):
                self.registry()

    def test_edition_requires_resolved_pinned_sources_and_reader_free_direct_files(self):
        for change, expected in (({"sha256": None}, "SHA-256 pinned"),
                                 ({"status": "unresolved"}, "resolved"),
                                 ({"reader_required": True}, "ordinary readable"),
                                 ({"destination": "SOFTWARE/pretend.txt"}, "ordinary readable")):
            before = self.assets[1]
            self.assets[1] = {**before, **change}
            with self.subTest(change=change), self.assertRaisesRegex(CatalogError, expected):
                self.registry()
            self.assets[1] = before

    def test_partial_edition_remains_incomplete(self):
        self.resource["editions"]["direct"].update(status="partial", reason="More selected books need editions")
        result = self.resolve(editions="collection=direct")
        self.assertEqual(result["incomplete_resources"][0]["reason"], "More selected books need editions")

    def test_fixed_profile_does_not_restore_replaced_published_assets(self):
        self.profile.pop("default_resources")
        for asset in self.assets[:3]:
            asset["profiles"] = ["test"]
        self.registry()
        selected, _, result = resolve_content(self.assets, self.profile, resources_path=self.registry_path,
                                               include="collection", editions="1=direct")
        self.assertEqual({a["id"] for a in selected}, {"critical", "direct"})
        self.assertEqual(result["baseline_asset_ids"], [])
        self.assertEqual(result["content_target_bytes"], 45)
        selected, _, result = resolve_content(self.assets, self.profile, resources_path=self.registry_path, exclude="collection")
        self.assertEqual(selected, [])  # Exclusion also covers the registered direct edition.

    def test_locked_selection_preserves_editions_and_validates_recorded_choice(self):
        result = self.resolve(editions="collection=direct")
        assets = result.pop("assets")
        lock = {"profile_id": "test", "content_selection": result}
        selected, _, selection = resolve_locked_content(assets, self.profile, lock)
        self.assertEqual(selection["explicit_editions"], {"collection": "direct"})
        self.assertEqual(capacity_plan(selected, self.profile, selection)["content_bytes"], 40)
        for editions in ([], {"collection": "unknown"}, {"unknown": "direct"}, {}):
            changed = {**result, "explicit_editions": editions}
            with self.subTest(editions=editions), self.assertRaisesRegex(CatalogError, "locked resource editions"):
                resolve_locked_content(assets, self.profile, {**lock, "content_selection": changed})

    def test_cli_applies_pinned_direct_edition_and_locked_catalog_rejects_override(self):
        # A real tiny direct build; the dummy archive is never opened or downloaded.
        data = b"An ordinary directly readable chapter about repair.\n"
        source = self.root / "source.txt"
        source.write_bytes(data)
        for asset in self.assets[:2]:
            asset.update(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), source_url=source.as_uri())
        self.registry()
        catalog = self.root / "catalog.yaml"
        catalog.write_text(yaml.safe_dump({"schema_version": 1, "assets": self.assets}), encoding="utf-8")
        profiles = self.root / "profiles"
        profiles.mkdir()
        (profiles / "test.yaml").write_text(yaml.safe_dump(self.profile), encoding="utf-8")
        target = self.root / "drive"
        args = [str(target), "--profile", "test", "--catalog", str(catalog), "--profiles-dir", str(profiles),
                "--resources-catalog", str(self.registry_path), "--allow-local", "--edition", "1=direct"]
        with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO) as error:
            self.assertEqual(main(args), 0, error.getvalue())
        inventory = json.loads((target / "LIBRARY/INVENTORY.json").read_text(encoding="utf-8"))
        self.assertEqual({a["id"] for a in inventory["assets"]}, {"critical", "direct"})
        self.assertEqual(inventory["content_selection"]["explicit_editions"], {"collection": "direct"})
        locked = target / "LIBRARY/LOCKED_CATALOG.yaml"
        args[args.index("--catalog") + 1] = str(locked)
        with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO) as error:
            self.assertEqual(main(args), 1)
            self.assertIn("not a locked selection", error.getvalue())
        with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO) as error:
            self.assertEqual(main([*args, "--list-resources"]), 1)
            self.assertIn("not a locked selection", error.getvalue())
        args = args[:-2]  # The lock already records the chosen direct edition.
        self.registry_path.unlink()
        with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO) as error:
            self.assertEqual(main(args), 0, error.getvalue())
        rebuilt = json.loads((target / "LIBRARY/INVENTORY.json").read_text(encoding="utf-8"))
        self.assertEqual(rebuilt["content_selection"]["explicit_editions"], {"collection": "direct"})


if __name__ == "__main__":
    unittest.main()
