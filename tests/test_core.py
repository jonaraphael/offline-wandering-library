from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from owl.build import build, check_space, check_space_groups
from owl.catalog import CatalogError, capacity_plan, load_catalog, load_profiles, select_profile
from owl.download import DownloadError, download, verified
from owl.safety import SafetyError, reject_symlinks, safe_path, sha256_file, validate_relative
from owl.verify import verify_drive


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.txt"
        self.data = b"OWL test fixture. Rainwater navigation agriculture repair.\n"
        self.source.write_bytes(self.data)
        self.asset = {"id": "fixture", "title": "Fixture", "category": "reference", "format": "txt",
                      "source_url": self.source.as_uri(), "destination": "REFERENCE/fixture.txt",
                      "version": "1", "size_bytes": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest(),
                      "license": "CC0-1.0", "redistributable": True, "required": True,
                      "critical": True, "profiles": ["test"]}
        self.profiles = self.root / "profiles"
        self.profiles.mkdir()
        self.profile = {"id": "test", "title": "Test", "capacity_bytes": 10**9,
                        "reserve_bytes": 0, "search_budget_bytes": 1024**2}
        (self.profiles / "test.yaml").write_text(yaml.safe_dump(self.profile))
        self.catalog = self.root / "catalog.yaml"
        self.write_catalog()

    def tearDown(self):
        self.temp.cleanup()

    def write_catalog(self, assets=None):
        self.catalog.write_text(yaml.safe_dump({"schema_version": 1, "assets": assets or [self.asset]}))

    def run_build(self, **kwargs):
        return build(self.root / "drive", catalog=self.catalog, profiles_dir=self.profiles,
                     profile_name="test", allow_local=True, progress=lambda _: None, **kwargs)


class CatalogTests(Fixture):
    def test_catalog_and_profile(self):
        profiles = load_profiles(self.profiles)
        assets = load_catalog(self.catalog, profiles, True)
        selected, unresolved = select_profile(assets, "test")
        self.assertEqual(selected[0]["id"], "fixture")
        self.assertEqual(unresolved, [])
        self.assertEqual(capacity_plan(assets, self.profile)["content_bytes"], len(self.data))

    def test_duplicate_and_case_colliding_paths(self):
        self.write_catalog([self.asset, {**self.asset, "id": "other", "destination": "REFERENCE/FIXTURE.TXT"}])
        with self.assertRaises(CatalogError):
            load_catalog(self.catalog, allow_local=True)

    def test_duplicate_yaml_keys(self):
        self.catalog.write_text("schema_version: 1\nschema_version: 1\nassets: []\n")
        with self.assertRaises(CatalogError):
            load_catalog(self.catalog)

    def test_critical_zim_and_unpinned_binary_rejected(self):
        for changes in ({"format": "zim", "reader_required": True},
                        {"destination": "SOFTWARE/reader.zip", "sha256": None, "critical": False}):
            self.write_catalog([{**self.asset, **changes}])
            with self.assertRaises(CatalogError):
                load_catalog(self.catalog, allow_local=True)

    def test_unresolved_optional_visible_and_required_fails(self):
        unresolved = {**self.asset, "status": "unresolved", "unresolved_reason": "Missing permission",
                      "required": False, "size_bytes": None, "source_url": None}
        self.write_catalog([unresolved])
        assets = load_catalog(self.catalog)
        self.assertEqual(select_profile(assets, "test"), ([], assets))
        assets[0]["required"] = True
        with self.assertRaises(CatalogError):
            select_profile(assets, "test")

    def test_decimal_capacity_and_headroom(self):
        profile = {**self.profile, "capacity_bytes": 512_000_000_000, "reserve_bytes": 51_200_000_000,
                   "search_budget_bytes": 100_000_000_000}
        with self.assertRaises(CatalogError):
            capacity_plan([{**self.asset, "size_bytes": 400_000_000_000}], profile)

    def test_local_sources_require_explicit_option(self):
        with self.assertRaises(CatalogError):
            load_catalog(self.catalog)


class SafetyTests(Fixture):
    def test_unsafe_paths(self):
        for path in ("../x", "/x", "a//x", "a/./x", "a/../x", "a\\x", "C:/x", "a/CON.txt", "a/x.", "a/x ", "a/x\ny", "a/é"):
            with self.subTest(path=path), self.assertRaises(SafetyError):
                validate_relative(path)

    def test_symlink_rejected(self):
        (self.root / "link").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(SafetyError):
            safe_path(self.root, "link/file")

    def test_windows_reparse_point_rejected_without_following_it(self):
        from types import SimpleNamespace
        with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=0, st_file_attributes=0x400)):
            with self.assertRaises(SafetyError):
                reject_symlinks(self.root / "junction")

    def test_insufficient_space(self):
        with patch("owl.build.shutil.disk_usage", return_value=type("Usage", (), {"free": 3})()):
            with self.assertRaisesRegex(SafetyError, "Insufficient"):
                check_space(self.root, 4)

    def test_space_allocations_on_same_filesystem_are_summed(self):
        with patch("owl.build.shutil.disk_usage", return_value=type("Usage", (), {"free": 100})()):
            with self.assertRaises(SafetyError):
                check_space_groups([(self.root / "cache", 60), (self.root / "work", 60)])

    def test_hash_and_existing_detection(self):
        self.assertTrue(verified(self.source, len(self.data), self.asset["sha256"]))
        self.assertFalse(verified(self.source, len(self.data), None))
        self.source.write_bytes(b"x" * len(self.data))
        self.assertFalse(verified(self.source, len(self.data), self.asset["sha256"]))


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {"Content-Length": str(len(data)), "ETag": '"version1"'}
        self.url = "https://example.org/fixture"


class DownloadTests(Fixture):
    def test_pinned_resume(self):
        dest = self.root / "download"
        dest.with_suffix(".part").write_bytes(self.data[:10])
        asset = {**self.asset, "source_url": "https://example.org/fixture"}
        response = Response(self.data[10:], 206, {"Content-Range": f"bytes 10-{len(self.data)-1}/{len(self.data)}", "ETag": '"v1"'})
        with patch("owl.download.urlopen", return_value=response) as open_url:
            self.assertEqual(download(asset, dest, repo_root=self.root, progress=lambda _: None), asset["sha256"])
            self.assertEqual(open_url.call_args.args[0].get_header("Range"), "bytes=10-")
        self.assertEqual(dest.read_bytes(), self.data)
        self.assertFalse(dest.with_suffix(".part").exists())

    def test_ignored_range_restarts(self):
        dest = self.root / "download"
        dest.with_suffix(".part").write_bytes(b"old")
        with patch("owl.download.urlopen", return_value=Response(self.data)):
            download({**self.asset, "source_url": "https://example.org/fixture"}, dest, repo_root=self.root, progress=lambda _: None)
        self.assertEqual(dest.read_bytes(), self.data)

    def test_bad_range_rejected(self):
        dest = self.root / "download"
        dest.with_suffix(".part").write_bytes(b"old")
        response = Response(self.data, 206, {"Content-Range": f"bytes 0-{len(self.data)-1}/{len(self.data)}"})
        with patch("owl.download.urlopen", return_value=response), self.assertRaises(DownloadError):
            download({**self.asset, "source_url": "https://example.org/fixture"}, dest, repo_root=self.root, retries=0, progress=lambda _: None)
        self.assertFalse(dest.exists())

    def test_checksum_failure_never_promotes(self):
        dest = self.root / "download"
        with patch("owl.download.urlopen", return_value=Response(b"x" * len(self.data))), self.assertRaises(DownloadError):
            download({**self.asset, "source_url": "https://example.org/fixture"}, dest, repo_root=self.root, retries=0, progress=lambda _: None)
        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_suffix(".part").exists())

    def test_retry_and_unpinned_conditional_resume(self):
        dest = self.root / "download"
        dest.with_suffix(".part").write_bytes(self.data[:10])
        dest.with_suffix(".part.json").write_text(json.dumps({"url": "https://example.org/fixture", "validator": '"v1"'}))
        response = Response(self.data[10:], 206, {"Content-Range": f"bytes 10-{len(self.data)-1}/{len(self.data)}", "ETag": '"v1"'})
        with patch("owl.download.urlopen", side_effect=[OSError("connection lost"), response]) as opened:
            download({**self.asset, "source_url": "https://example.org/fixture", "sha256": None}, dest,
                     repo_root=self.root, retries=1, sleep=lambda _: None, progress=lambda _: None)
            self.assertEqual(opened.call_args.args[0].get_header("If-range"), '"v1"')
        self.assertEqual(dest.read_bytes(), self.data)

    def test_unpinned_changed_validator_restarts_instead_of_combining_versions(self):
        dest = self.root / "download"
        dest.with_suffix(".part").write_bytes(b"x" * 10)
        dest.with_suffix(".part.json").write_text(json.dumps({"url": "https://example.org/fixture", "validator": '"v1"'}))
        changed = Response(self.data[10:], 206, {"Content-Range": f"bytes 10-{len(self.data)-1}/{len(self.data)}", "ETag": '"v2"'})
        with patch("owl.download.urlopen", side_effect=[changed, Response(self.data)]) as opened:
            download({**self.asset, "source_url": "https://example.org/fixture", "sha256": None}, dest,
                     repo_root=self.root, retries=1, sleep=lambda _: None, progress=lambda _: None)
            self.assertIsNone(opened.call_args.args[0].get_header("Range"))
        self.assertEqual(dest.read_bytes(), self.data)


class BuildTests(Fixture):
    def test_end_to_end_idempotent_and_independent_verification(self):
        self.run_build()
        drive = self.root / "drive"
        initial = sha256_file(drive / "SEARCH/library.owl")
        content = drive / self.asset["destination"]
        mtime = content.stat().st_mtime_ns
        (drive / "personal.txt").write_text("preserve me")
        with patch("owl.build.download", side_effect=AssertionError("must reuse")):
            self.run_build()
        self.assertEqual(content.stat().st_mtime_ns, mtime)
        self.assertEqual(sha256_file(drive / "SEARCH/library.owl"), initial)
        result = verify_drive(drive, emit=lambda _: None)
        self.assertGreater(result["OK"], 30)
        self.assertEqual(result["UNKNOWN"], 1)
        self.assertEqual(result["FAILED"] + result["MISSING"], 0)
        self.assertTrue(json.loads((drive / ".owl/state.json").read_text())["complete"])
        locked = load_catalog(drive / "LOCKED_CATALOG.yaml", allow_local=True)
        self.assertEqual(locked[0]["sha256"], self.asset["sha256"])
        content.write_text("damaged")
        self.assertEqual(verify_drive(drive, emit=lambda _: None)["FAILED"], 1)
        content.unlink()
        self.assertEqual(verify_drive(drive, emit=lambda _: None)["MISSING"], 1)
        self.run_build()
        self.assertEqual(content.read_bytes(), self.data)

    def test_cache_rebuild_second_drive_without_source(self):
        cache = self.root / "cache"
        self.run_build(cache_dir=cache)
        self.source.unlink()
        with patch("owl.build.download", side_effect=AssertionError("must use cache")):
            build(self.root / "second", catalog=self.catalog, profiles_dir=self.profiles, profile_name="test",
                  cache_dir=cache, allow_local=True, progress=lambda _: None)
        self.assertEqual((self.root / "second" / self.asset["destination"]).read_bytes(), self.data)

    def test_unowned_conflict_and_symlink_do_not_overwrite(self):
        target = self.root / "drive"
        target.mkdir()
        (target / "START_HERE.html").write_text("personal")
        with self.assertRaises(SafetyError):
            self.run_build()
        self.assertEqual((target / "START_HERE.html").read_text(), "personal")

    def test_plan_and_insufficient_space_write_nothing(self):
        self.run_build(plan_only=True)
        self.assertFalse((self.root / "drive").exists())
        with patch("owl.build.shutil.disk_usage", return_value=type("Usage", (), {"free": 1})()):
            with self.assertRaises(SafetyError):
                self.run_build()
        self.assertFalse((self.root / "drive").exists())

    def test_verifier_rejects_manifest_traversal(self):
        drive = self.root / "drive"
        drive.mkdir()
        (drive / "SHA256SUMS.txt").write_text("0" * 64 + "  ../source.txt\n")
        self.assertEqual(verify_drive(drive, emit=lambda _: None)["FAILED"], 1)

    def test_verifier_reports_interrupted_build_even_if_files_match(self):
        self.run_build()
        state_path = self.root / "drive/.owl/state.json"
        state = json.loads(state_path.read_text())
        state["complete"] = False
        state_path.write_text(json.dumps(state))
        self.assertEqual(verify_drive(self.root / "drive", emit=lambda _: None)["FAILED"], 1)


if __name__ == "__main__":
    unittest.main()
