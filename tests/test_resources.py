"""Resource plans are transparent about selection, missing sources, and budgets."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import yaml

from owl.catalog import CatalogError
from owl.resources import load_resources, resolve_resources


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "resources.yaml"
        self.assets = [
            self.asset("core", 10), self.asset("book_a", 30), self.asset("book_b", 40),
            self.asset("wikipedia", 127, format="zim", destination="ZIM/wiki.zim"),
            self.asset("reader", 2, format="exe", destination="SOFTWARE/reader.exe"),
            self.asset("map_na", 21), self.asset("map_topo", 30), self.asset("map_world", 72),
            self.asset("missing", None, status="unresolved"),
        ]
        self.rows = [
            self.resource("owl-direct-core", None, 10, ["core"]),
            self.resource("wikipedia", 1, 119, ["wikipedia"]),
            self.resource("textbooks", 22, 50, ["book_a", "book_b"]),
            self.resource("medical", 3, 20, ["book_a"], status="partial", reason="More medical sources need pins"),
            self.resource("regional-maps", 14, 51, ["map_na", "map_topo"]),
            self.resource("world-maps", 42, 72, ["map_world"],
                          replaces_asset_ids=["map_na"],
                          replacement_credit={"resource_id": "regional-maps", "target_bytes": 21}),
            self.resource("unsourced", 8, 100, [], status="unresolved", reason="No approved source"),
            self.resource("archive-readers", None, 0, ["reader"]),
        ]
        self.profile = {"id": "compact", "default_resources": ["owl-direct-core", "textbooks"],
                        "readers_budget_bytes": 5}

    @staticmethod
    def asset(identity, size, **extra):
        return {"id": identity, "size_bytes": size, "status": "resolved", "format": "pdf",
                "destination": f"BOOKS/{identity}.pdf", "profiles": ["old-profile"],
                "required": True, **extra}

    @staticmethod
    def resource(identity, number, target, members, **extra):
        return {"id": identity, "number": number, "title": identity.title(), "target_bytes": target,
                "status": "ready", "asset_ids": members, **extra}

    def registry(self, rows=None):
        self.path.write_text(yaml.safe_dump({"schema_version": 1, "resources": self.rows if rows is None else rows}),
                             encoding="utf-8", newline="\n")
        return load_resources(self.path, self.assets)

    def resolve(self, **kwargs):
        return resolve_resources(self.assets, self.profile, self.registry(), **kwargs)

    def test_defaults_and_known_sizes_keep_declared_estimates_visible(self):
        result = self.resolve()
        self.assertEqual(result["selected_ids"], ["owl-direct-core", "textbooks"])
        self.assertEqual(result["declared_content_target_bytes"], 60)
        self.assertEqual(result["content_target_bytes"], 80)
        self.assertEqual(result["resolved_asset_bytes"], 80)
        row = result["resource_rows"][1]
        self.assertEqual((row["target_bytes"], row["known_bytes"], row["effective_target_bytes"]), (50, 70, 70))
        self.assertFalse(result["customized"])
        self.assertEqual(result["incomplete_resources"], [])
        self.assertEqual(result["readers_budget_bytes"], 0)

    def test_repeated_and_comma_selections_accept_numbers_and_ids(self):
        result = self.resolve(include=("1, 3", "wikipedia", 22), exclude=("owl-direct-core",))
        self.assertEqual(result["explicit_include"], ["wikipedia", "textbooks", "medical"])
        self.assertEqual(result["selected_ids"], ["wikipedia", "textbooks", "medical", "archive-readers"])
        self.assertEqual(result["excluded_ids"], ["owl-direct-core"])
        self.assertEqual(result["auto_included_ids"], ["archive-readers"])
        self.assertEqual(result["incomplete_resources"][0]["id"], "medical")
        self.assertTrue(result["customized"])

    def test_member_aliases_deduplicate_files_and_annotate_all_owners(self):
        before = deepcopy(self.assets)
        result = self.resolve(include="3")
        books = [asset for asset in result["assets"] if asset["id"] == "book_a"]
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["resource_ids"], ["textbooks", "medical"])
        self.assertIn("compact", books[0]["profiles"])
        self.assertEqual(result["resolved_asset_bytes"], 80)
        self.assertEqual(self.assets, before)

    def test_explicit_exclusion_removes_required_member_assets(self):
        result = self.resolve(exclude="textbooks,owl-direct-core")
        self.assertEqual(result["assets"], [])
        self.assertEqual(result["selected_ids"], [])
        self.assertEqual(result["planned_total_bytes"], 0)

    def test_include_exclude_alias_collision_is_an_error(self):
        with self.assertRaisesRegex(CatalogError, "both included and excluded"):
            self.resolve(include="22", exclude="textbooks")

    def test_unknown_and_empty_selections_are_errors(self):
        for selection in ("999", "unknown", "22,", True):
            with self.subTest(selection=selection), self.assertRaises(CatalogError):
                self.resolve(include=[selection])

    def test_reader_dependency_and_budget_are_added_for_resolved_zim(self):
        result = self.resolve(include="1", exclude="textbooks")
        self.assertEqual(result["content_target_bytes"], 137)
        self.assertEqual(result["readers_budget_bytes"], 5)
        self.assertEqual(result["planned_total_bytes"], 142)
        self.assertEqual(result["resolved_asset_bytes"], 139)
        self.assets[4]["size_bytes"] = 8
        result = self.resolve(include="wikipedia")
        self.assertEqual(result["readers_budget_bytes"], 8)

    def test_explicit_reader_exclusion_with_zim_is_an_error(self):
        with self.assertRaisesRegex(CatalogError, "need archive-readers"):
            self.resolve(include="1", exclude="archive-readers")

    def test_missing_reader_resource_and_empty_override_are_errors(self):
        registry = self.registry(self.rows[:-1])
        with self.assertRaisesRegex(CatalogError, "missing from the registry"):
            resolve_resources(self.assets, self.profile, registry, include="1")
        self.profile["resource_overrides"] = {"archive-readers": {"exclude_asset_ids": ["reader"]}}
        with self.assertRaisesRegex(CatalogError, "resolved bundled reader"):
            self.resolve(include="1")

    def test_unresolved_zim_is_incomplete_without_auto_adding_readers(self):
        self.assets[3]["status"] = "unresolved"
        self.rows[1].update(status="unresolved", reason="Snapshot not pinned")
        result = self.resolve(include="1")
        self.assertNotIn("archive-readers", result["selected_ids"])
        self.assertEqual(result["unresolved_asset_ids"], ["wikipedia"])
        self.assertEqual(result["incomplete_resources"][0]["id"], "wikipedia")

    def test_unsourced_collections_keep_their_budget_and_explicit_reason(self):
        result = self.resolve(include="unsourced")
        row = result["incomplete_resources"][0]
        self.assertEqual(row["id"], "unsourced")
        self.assertEqual(row["effective_target_bytes"], 100)
        self.assertEqual(row["known_bytes"], 0)
        self.assertIn("No approved source", row["reason"])
        self.assertEqual(result["content_target_bytes"], 180)

    def test_profile_overrides_remove_only_the_named_resource_members(self):
        self.profile["resource_overrides"] = {"textbooks": {"target_bytes": 45, "exclude_asset_ids": ["book_a"]}}
        result = self.resolve(include="medical")
        textbook = next(row for row in result["resource_rows"] if row["id"] == "textbooks")
        self.assertEqual(textbook["asset_ids"], ["book_b"])
        self.assertEqual(textbook["planning_target_bytes"], 45)
        self.assertEqual(textbook["effective_target_bytes"], 45)
        book = next(asset for asset in result["assets"] if asset["id"] == "book_a")
        self.assertEqual(book["resource_ids"], ["medical"])

    def test_world_maps_replace_regional_payload_and_only_credit_selected_na(self):
        self.profile["default_resources"] = ["regional-maps", "world-maps"]
        result = self.resolve()
        self.assertEqual({asset["id"] for asset in result["assets"]}, {"map_topo", "map_world"})
        self.assertEqual(result["replaced_asset_ids"], ["map_na"])
        self.assertEqual(result["content_target_bytes"], 102)
        self.assertEqual(result["resource_rows"][0]["credit_bytes"], 21)
        self.assertEqual(result["resource_rows"][0]["known_bytes"], 30)
        self.profile["resource_overrides"] = {"regional-maps": {"target_bytes": 10, "exclude_asset_ids": ["map_na", "map_topo"]}}
        result = self.resolve()
        self.assertEqual(result["resource_rows"][0]["credit_bytes"], 0)
        self.assertEqual(result["content_target_bytes"], 82)
        result = self.resolve(exclude="14")
        self.assertEqual(result["content_target_bytes"], 72)

    def test_replacement_uses_remaining_known_size_not_estimated_removed_size(self):
        self.assets[5]["size_bytes"] = 100  # Replaced actual size differs from its 21-byte estimate.
        self.profile["default_resources"] = ["regional-maps", "world-maps"]
        result = self.resolve()
        self.assertEqual(result["content_target_bytes"], 102)
        self.assertEqual(result["resolved_asset_bytes"], 102)

    def test_compact_map_override_avoids_credit_for_excluded_north_america(self):
        self.assets[6].update(status="unresolved", size_bytes=None)
        self.rows[4].update(status="unresolved", reason="Regional topographic source not pinned")
        self.profile["default_resources"] = ["regional-maps", "world-maps"]
        self.profile["resource_overrides"] = {"regional-maps": {"target_bytes": 10, "exclude_asset_ids": ["map_na"]}}
        result = self.resolve()
        regional = result["resource_rows"][0]
        self.assertEqual(regional["asset_ids"], ["map_topo"])
        self.assertEqual(regional["credit_bytes"], 0)
        self.assertEqual(regional["effective_target_bytes"], 10)
        self.assertEqual(result["content_target_bytes"], 82)
        self.assertEqual(result["unresolved_asset_ids"], ["map_topo"])

    def test_resource_schema_version_must_be_an_integer(self):
        self.path.write_text(yaml.safe_dump({"schema_version": True, "resources": self.rows}), encoding="utf-8")
        with self.assertRaisesRegex(CatalogError, "schema_version"):
            load_resources(self.path, self.assets)

    def test_credit_cannot_make_target_negative(self):
        self.profile["default_resources"] = ["regional-maps", "world-maps"]
        self.profile["resource_overrides"] = {"regional-maps": {"target_bytes": 10}}
        with self.assertRaisesRegex(CatalogError, "credit exceeds"):
            self.resolve()

    def test_conflicting_replacement_resources_are_rejected(self):
        self.rows.append(self.resource("other-world", 43, 72, ["map_world"], replaces_asset_ids=["map_na"]))
        self.profile["default_resources"] = ["regional-maps", "world-maps", "other-world"]
        with self.assertRaisesRegex(CatalogError, "both replace"):
            self.resolve()

    def test_profile_without_defaults_resolves_only_explicit_resources(self):
        del self.profile["default_resources"]
        self.assertEqual(self.resolve()["assets"], [])
        self.assertEqual(self.resolve(include="22")["selected_ids"], ["textbooks"])

    def test_registry_rejects_unknown_assets_duplicate_numbers_and_unsafe_ids(self):
        mutations = [
            {"asset_ids": ["does_not_exist"]}, {"id": "../escape"},
            {"number": 22}, {"number": True}, {"target_bytes": True},
            {"target_bytes": -1}, {"status": ["ready"]},
            {"status": "partial", "reason": ""}, {"asset_ids": []},
            {"asset_ids": ["missing"]}, {"asset_ids": ["core", "core"]},
            {"source_pages": ["http://example.com"]},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                rows = deepcopy(self.rows)
                rows[0].update(mutation)
                with self.assertRaises(CatalogError):
                    self.registry(rows)
        with self.assertRaisesRegex(CatalogError, "duplicate resource id"):
            self.registry([*self.rows, self.rows[0]])

    def test_registry_rejects_unknown_credit_and_wrong_replacement_members(self):
        for credit in ({"resource_id": "unknown", "target_bytes": 21},
                       {"resource_id": "textbooks", "target_bytes": 21}):
            rows = deepcopy(self.rows)
            rows[5]["replacement_credit"] = credit
            with self.assertRaises(CatalogError):
                self.registry(rows)

    def test_invalid_defaults_overrides_and_reader_budgets_are_rejected(self):
        cases = [
            {"default_resources": ["unknown"]}, {"default_resources": ["textbooks", "textbooks"]},
            {"resource_overrides": {"unknown": {}}},
            {"resource_overrides": {"textbooks": {"exclude_asset_ids": ["core"]}}},
            {"resource_overrides": {"textbooks": {"target_bytes": 3.5}}},
            {"readers_budget_bytes": -1},
        ]
        registry = self.registry()
        for change in cases:
            with self.subTest(change=change), self.assertRaises(CatalogError):
                resolve_resources(self.assets, {**self.profile, **change}, registry)


if __name__ == "__main__":
    unittest.main()
