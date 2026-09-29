"""The same content rules apply to old catalogs, new fragments and build inputs."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

from owl import content_policy
from owl.build import build
from owl.catalog import CatalogError, DIRECT, main as validate_main
from owl.acquisition.cli import stage


def asset(**changes):
    return dict(dict(id='book', title='Book', category='reference', format='pdf',
        source_url='https://example.org/book.pdf', destination='BOOKS/book.pdf',
        version='1', size_bytes=10, sha256='a' * 64, license='CC0',
        redistributable=True, required=True, profiles=['test']), **changes)


class PolicyTests(unittest.TestCase):
    def audit(self, **changes):
        return content_policy.audit_assets([asset(**changes)])

    def test_finished_pdf_needs_no_conversion(self):
        self.assertTrue(self.audit()['compliant'])

    def test_unknown_format_cannot_pass_even_with_valid_pins(self):
        for fmt in ('docx', 'db', 'pbf', 'py', 'whatever'):
            with self.subTest(fmt=fmt):
                self.assertFalse(self.audit(format=fmt)['compliant'])

    def test_generation_is_rejected_even_for_pdf_or_companion(self):
        for supporting in (True, False):
            report = self.audit(generation={'recipe_id': 'approved-old-recipe'}, supporting_file=supporting)
            self.assertIn('processing_forbidden', {v['rule'] for v in report['violations']})

    def test_unpacking_unchanged_pdf_is_allowed(self):
        self.assertTrue(self.audit(archive_member={'source_asset_id': 'zip', 'path': 'book.pdf', 'document': True})['compliant'])

    def test_delivery_package_is_not_reading_content(self):
        self.assertFalse(self.audit(format='zip')['compliant'])
        self.assertTrue(self.audit(format='zip', supporting_file=True)['compliant'])

    def test_html_requires_explicit_offline_review_and_strict_boolean(self):
        for value in (None, False, 'true', 1):
            self.assertFalse(self.audit(format='html', offline_ready=value)['compliant'])
        self.assertTrue(self.audit(format='html', offline_ready=True)['compliant'])

    def test_epub_is_only_an_optional_reading_edition_not_conversion_input(self):
        self.assertFalse(self.audit(format='epub')['compliant'])
        self.assertTrue(self.audit(format='epub', optional_format=True, required=False, reader_required=True)['compliant'])
        self.assertFalse(self.audit(format='epub', optional_format=True, required=False, reader_required=True, supporting_file=True)['compliant'])

    def test_media_container_requires_compatible_codec(self):
        self.assertFalse(self.audit(format='mp4')['compliant'])
        self.assertFalse(self.audit(format='mp4', video_codec='hevc', audio_codec='aac')['compliant'])
        self.assertTrue(self.audit(format='mp4', video_codec='h264', audio_codec='aac')['compliant'])
        self.assertTrue(self.audit(format='mp4', video_codec='h264', audio_codec='none')['compliant'])

    def test_zim_requires_reader_and_software_packages_are_allowed(self):
        self.assertFalse(self.audit(format='zim')['compliant'])
        self.assertTrue(self.audit(format='zim', reader_required=True)['compliant'])
        self.assertTrue(self.audit(format='zip', destination='SOFTWARE/reader.zip')['compliant'])

    def test_companion_files_are_not_reading_entries(self):
        self.assertFalse(self.audit(format='css')['compliant'])
        self.assertTrue(self.audit(format='css', supporting_file=True)['compliant'])
        self.assertFalse(self.audit(format='css', artifact_role='companion')['compliant'])

    def test_prebuilt_search_payload_must_be_browser_ready(self):
        self.assertFalse(self.audit(format='bin', artifact_role='search_index')['compliant'])
        self.assertTrue(self.audit(format='bin', artifact_role='search_index', browser_ready=True)['compliant'])

    def test_explicit_reprocessing_or_access_dependencies_rejected(self):
        for changes in ({'materialization': 'convert'}, {'requires_server': True},
                        {'drm': True}, {'password_required': True}, {'requires_network': True}):
            self.assertFalse(self.audit(**changes)['compliant'])

    def test_unpinned_unresolved_and_duplicate_records_fail(self):
        for changes in ({'sha256': None}, {'status': 'unresolved'}, {'size_bytes': True}):
            self.assertFalse(self.audit(**changes)['compliant'])
        self.assertFalse(content_policy.audit_assets([asset(), asset()])['compliant'])

    def test_policy_changes_drive_checks_and_direct_reading_classification(self):
        policy = content_policy.load_policy()
        self.assertEqual(DIRECT, set(policy['direct_reading_formats']))
        changed = deepcopy(policy)
        changed['roles']['document'].remove('pdf')
        with patch.object(content_policy, 'load_policy', return_value=changed):
            self.assertFalse(self.audit()['compliant'])

    def test_invalid_and_duplicate_policy_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'policy.json'
            for value in ('{}', '{"schema_version":1,"schema_version":1}'):
                path.write_text(value)
                with patch.object(content_policy, 'POLICY_PATH', path), self.assertRaises(ValueError):
                    content_policy.load_policy()


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.profiles = self.root / 'profiles'
        self.profiles.mkdir()
        self.profile = dict(id='test', capacity_bytes=100_000_000, reserve_bytes=0, discovery_budget_bytes=1_000_000)
        (self.profiles / 'test.yaml').write_text(yaml.safe_dump(self.profile))
        self.source = self.root / 'book.txt'
        self.source.write_bytes(b'Finished ordinary text fixture.\n')
        self.good = asset(format='txt', destination='BOOKS/book.txt', source_url=self.source.as_uri(),
                          size_bytes=self.source.stat().st_size, sha256=hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.catalog = self.root / 'library.yaml'
        self.target = self.root / 'drive'
        self.write([self.good])

    def write(self, assets):
        self.catalog.write_text(yaml.safe_dump({'schema_version': 1, 'assets': assets}))

    def run_build(self, **kwargs):
        return build(self.target, catalog=self.catalog, profiles_dir=self.profiles,
                     profile_name='test', allow_local=True, progress=lambda _: None, **kwargs)

    def test_plain_finished_file_still_builds_and_verifies(self):
        result = self.run_build()
        self.assertTrue(result['complete'])
        self.assertEqual((self.target / 'LIBRARY/BOOKS/book.txt').read_bytes(), self.source.read_bytes())

    def test_build_plan_and_partial_flag_cannot_bypass_policy(self):
        self.write([{**self.good, 'format': 'docx'}])
        for kwargs in ({}, {'plan_only': True}, {'allow_incomplete': True}):
            with patch('owl.build.download', side_effect=AssertionError('must not download')), self.assertRaisesRegex(CatalogError, 'Content policy'):
                self.run_build(**kwargs)
            self.assertFalse(self.target.exists())

    def test_extra_catalog_cannot_bypass_policy(self):
        extra = self.root / 'extra.yaml'
        extra.write_text(yaml.safe_dump({'assets': [{**self.good, 'id': 'extra', 'format': 'docx', 'destination': 'BOOKS/extra.docx'}]}))
        with self.assertRaisesRegex(CatalogError, 'Content policy'):
            self.run_build(extra_catalogs=[extra])
        self.assertFalse(self.target.exists())

    def test_approved_generated_pdf_is_rejected_before_download(self):
        output = {**self.good, 'id': 'converted', 'format': 'pdf', 'destination': 'BOOKS/converted.pdf',
                  'generation': {'recipe_id': 'conversion'}}
        recipe = dict(id='conversion', resource_id='core', adapter='html_snapshot', version='1',
                      source_asset_ids=['book'], output_asset_ids=['converted'], selection={},
                      review={'status': 'approved', 'evidence': ['fixture review']}, blockers=[])
        self.catalog.write_text(yaml.safe_dump({'schema_version': 1, 'assets': [self.good, output],
                                                'acquisition_recipes': [recipe]}))
        with patch('owl.build.download', side_effect=AssertionError('must not download')), self.assertRaisesRegex(CatalogError, 'build-time processing'):
            self.run_build()
        self.assertFalse(self.target.exists())

    def test_cli_checks_existing_catalog_and_returns_json(self):
        self.write([{**self.good, 'format': 'docx'}])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(content_policy.main([str(self.catalog)]), 1)
        self.assertEqual(json.loads(output.getvalue())['catalogs'][0]['noncompliant_assets'], 1)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(validate_main([str(self.catalog), '--profiles-dir', str(self.profiles), '--allow-local']), 1)

    def test_audit_invalid_yaml_returns_machine_readable_error(self):
        self.catalog.write_text('assets: [')
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(content_policy.main([str(self.catalog)]), 2)
        self.assertFalse(json.loads(output.getvalue())['compliant'])

    def test_candidate_staging_fails_before_creating_output(self):
        fragment = self.root / 'fragment.yaml'
        fragment.write_text(yaml.safe_dump({'schema_version': 1, 'assets': [asset(id='new', format='docx', destination='BOOKS/new.docx')]}))
        args = SimpleNamespace(fragment=fragment, catalog=self.catalog, review_receipt=None,
                               resource=[], profile=[], allow_local=True, output=self.root / 'candidate')
        context = ([self.good], {}, {'test': self.profile}, {}, set(), {})
        with self.assertRaisesRegex(CatalogError, 'Content policy'):
            stage(args, context)
        self.assertFalse(args.output.exists())
