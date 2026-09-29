"""Assemble the reusable metadata only for verified, completed downloads."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import yaml

from test_atlas_build import AtlasBuildFixture
from owl.catalog import CatalogError, load_catalog, resolve_locked_content
from owl.discovery import main
from owl.postflight import audit_build
from owl.safety import SafetyError
from owl.verify import verify_drive


class AvailableDiscoveryTests(AtlasBuildFixture):
    def configure(self):
        self.second_bytes = b'Another completely downloaded document.'
        self.second = {**self.asset, 'id': 'later', 'title': 'Later arrival',
                       'destination': 'REFERENCE/later.txt', 'size_bytes': len(self.second_bytes),
                       'sha256': hashlib.sha256(self.second_bytes).hexdigest()}
        self.write_catalog([self.asset, self.second])
        self.topic_data['topics'].append({'id': 'later-topic', 'title': 'Later topic',
            'description': 'Appears only after its source finishes', 'parents': ['subject']})
        (self.nav / 'topics.yaml').write_text(yaml.safe_dump(self.topic_data))
        self.assignments['assignments'].append({'asset_id': 'later', 'topic_id': 'later-topic'})
        self.write_assignments()
        self.put_downloaded_files()
        self.later = self.library / self.second['destination']

    def assembled(self):
        self.atlas(profile='test', from_downloads=True)
        return json.loads((self.library / 'INVENTORY.json').read_text())

    def test_unpinned_download_is_rejected_before_publication(self):
        self.asset['sha256'] = None
        self.write_catalog()
        self.put_downloaded_files()
        with self.assertRaisesRegex(CatalogError, 'Content policy'):
            self.assembled()
        self.assertFalse((self.drive / 'START_HERE.html').exists())
        self.assertFalse((self.library / 'INVENTORY.json').exists())

    def test_non_offline_html_is_rejected_before_publication(self):
        self.asset.update(format='html', offline_ready=False, destination='REFERENCE/fixture.html')
        self.write_catalog()
        self.put_downloaded_files()
        with self.assertRaisesRegex(CatalogError, 'Content policy'):
            self.assembled()
        self.assertFalse((self.drive / 'START_HERE.html').exists())

    def test_saved_publication_cannot_bypass_content_policy(self):
        self.configure()
        with patch('owl.atlas_build.write_outputs', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.assembled()
        checkpoint = self.library / '.owl/atlas-job.json'
        job = json.loads(checkpoint.read_text())
        for change, error, message in (({'requires_network': True}, CatalogError, 'Content policy'),
                                       ({'verification': 'observed'}, SafetyError, 'catalog-pinned')):
            with self.subTest(change=change):
                original = job['inventory']['assets'][0]
                job['inventory']['assets'][0] = {**original, **change}
                checkpoint.write_text(json.dumps(job))
                with self.assertRaisesRegex(error, message):
                    self.assembled()
                job['inventory']['assets'][0] = original
        self.assertFalse((self.drive / 'START_HERE.html').exists())

    def test_reassembling_completed_named_resource_build_passes_postflight(self):
        (self.profiles / 'test.yaml').write_text(yaml.safe_dump({**self.profile, 'default_resources': ['core']}))
        (self.catalog.parent / 'resources.yaml').write_text(yaml.safe_dump({'schema_version': 1,
            'resources': [{'id': 'core', 'title': 'Core', 'status': 'ready', 'target_bytes': len(self.data),
                           'asset_ids': ['fixture']}]}))
        self.run_build(navigation_dir=self.nav)
        self.assertEqual(audit_build(self.drive, run_smoke=False)['status'], 'passed')
        inventory = self.assembled()
        report = audit_build(self.drive, run_smoke=False)
        self.assertEqual(report['status'], 'passed')
        self.assertTrue(report['selection']['content_complete'])
        info = json.loads((self.library / 'BUILD_INFO.json').read_text())
        self.assertEqual(info['content_selection'], inventory['content_selection'])
        state = json.loads((self.library / '.owl/state.json').read_text())
        self.assertEqual(state['result']['status'], 'passed')
        self.assertEqual(state['result']['selection'], report['selection'])
        self.check_verified()

    def test_postflight_failure_leaves_assembly_resumable_and_incomplete(self):
        self.configure()
        with patch('owl.postflight.audit_build', side_effect=SafetyError('Postflight failure')):
            with self.assertRaisesRegex(SafetyError, 'Postflight failure'):
                self.assembled()
        state = json.loads((self.library / '.owl/state.json').read_text())
        self.assertFalse(state['complete'])
        self.assertNotIn('result', state)
        self.assertTrue((self.library / '.owl/atlas-job.json').is_file())
        self.assembled()
        state = json.loads((self.library / '.owl/state.json').read_text())
        self.assertTrue(state['complete'])
        self.assertEqual(state['result']['status'], 'passed')
        self.assertFalse((self.library / '.owl/atlas-job.json').exists())

    def test_partial_bad_and_missing_downloads_are_excluded_then_success_is_added(self):
        self.configure()
        self.later.with_suffix('.txt.part').write_bytes(self.second_bytes[:8])
        for data in (None, b'short partial', b'X' * len(self.second_bytes)):
            if data is not None:
                self.later.write_bytes(data)
            inventory = self.assembled()
            self.assertEqual([a['id'] for a in inventory['assets']], ['fixture'])
            self.assertFalse(inventory['content_complete'])
            self.assertIn('later', {a['id'] for a in inventory['unresolved']})
            self.assertNotIn('later-topic', inventory['navigation']['included_topic_ids'])
            self.assertNotIn('later', {r['id'] for r in inventory['search']['assets']})
        self.later.write_bytes(self.second_bytes)
        inventory = self.assembled()
        self.assertEqual({a['id'] for a in inventory['assets']}, {'fixture', 'later'})
        self.assertTrue(inventory['content_complete'])
        self.assertIn('later-topic', inventory['navigation']['included_topic_ids'])
        counts = verify_drive(self.drive, emit=lambda _: None)
        self.assertEqual(counts['FAILED'] + counts['MISSING'], 0)
        self.assertTrue(self.later.with_suffix('.txt.part').exists())
        # A source that later disappears is no longer linked or checksum-listed.
        self.later.unlink()
        inventory = self.assembled()
        self.assertNotIn('later-topic', inventory['navigation']['included_topic_ids'])
        self.assertIn('Unavailable in this build', (self.library / 'INDEX/topics/later-topic.html').read_text())
        self.assertNotIn(self.second['destination'], (self.library / 'SHA256SUMS.txt').read_text())
        self.assertEqual(verify_drive(self.drive, emit=lambda _: None)['MISSING'], 0)

    def test_source_audit_is_once_per_admission_and_compiler_is_metadata_only(self):
        self.configure()
        from owl.atlas_build import sha256_file
        calls = []
        def audited(path):
            calls.append(path)
            return sha256_file(path)
        with patch('owl.atlas_build.sha256_file', side_effect=audited):
            inventory = self.assembled()
        self.assertEqual(calls.count(self.library / self.asset['destination']), 1)
        self.assertEqual(inventory['search']['source_body_bytes_read'], 0)

    def test_named_resource_scope_and_locked_catalog_reflect_only_available_assets(self):
        self.configure()
        profile = {**self.profile, 'default_resources': ['core']}
        (self.profiles / 'test.yaml').write_text(yaml.safe_dump(profile))
        (self.catalog.parent / 'resources.yaml').write_text(yaml.safe_dump({'schema_version': 1,
            'resources': [{'id': 'core', 'title': 'Core', 'status': 'ready', 'target_bytes': 1000,
                           'asset_ids': ['fixture', 'later']}]}))
        inventory = self.assembled()
        row = inventory['content_selection']['resource_rows'][0]
        self.assertEqual(row['resolved_asset_ids'], ['fixture'])
        self.assertEqual(row['status'], 'partial')
        locked = self.library / 'LOCKED_CATALOG.yaml'
        lock = json.loads(locked.read_text())['selection_lock']
        selected, _, scope = resolve_locked_content(load_catalog(locked, allow_local=True), profile, lock)
        self.assertEqual([a['id'] for a in selected], ['fixture'])
        self.assertTrue(scope['incomplete_resources'])
        report = audit_build(self.drive, run_smoke=False)
        self.assertEqual(report['status'], 'passed')
        self.assertFalse(report['selection']['content_complete'])
        self.assertEqual(report['selection']['assets'], 1)

    def test_assemble_cli_needs_no_previous_inventory_and_never_downloads(self):
        self.configure()
        with patch('owl.build.download', side_effect=AssertionError('network')):
            result = main(['assemble', '--output', str(self.drive), '--profile', 'test',
                           '--catalog', str(self.catalog), '--profiles-dir', str(self.profiles),
                           '--navigation-dir', str(self.nav), '--allow-local'])
        self.assertEqual(result, 0)
        self.assertTrue((self.drive / 'START_HERE.html').is_file())

    def test_interrupted_full_build_stays_incomplete_and_empty_drive_is_not_published(self):
        self.configure()
        from owl.build import _owned_directory
        _owned_directory(self.library / '.owl')
        (self.library / '.owl/state.json').write_text(json.dumps({'schema_version': 1,
            'managed': [], 'assets': {}, 'complete': False, 'phase': 'content'}))
        self.assembled()
        state = json.loads((self.library / '.owl/state.json').read_text())
        self.assertFalse(state['complete'])
        self.assertIn('build-incomplete', state['phase'])
        (self.library / self.asset['destination']).unlink()
        with self.assertRaisesRegex(SafetyError, 'No selected catalog files'):
            self.assembled()

    def test_interrupted_assembly_resumes_and_allows_metadata_only_refresh(self):
        self.configure()
        with patch('owl.atlas_build.write_outputs', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.assembled()
        with self.assertRaisesRegex(SafetyError, 'same source-verification mode'):
            self.atlas()
        with self.assertRaisesRegex(SafetyError, 'same source-verification mode'):
            self.atlas(profile='other', from_downloads=True)
        self.assembled()
        self.check_verified()
        source = (self.library / self.asset['destination']).resolve()
        original = Path.open
        def guard(path, *args, **kwargs):
            if path.resolve() == source:
                raise AssertionError('Metadata refresh opened a source')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guard):
            self.atlas(metadata_only=True)
        self.check_verified()
