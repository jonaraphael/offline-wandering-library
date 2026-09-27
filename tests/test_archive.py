"""ZIP packaging tests use only tiny synthetic local archives, never downloads."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import yaml

from owl.archive import ArchiveError, ZipSource, order_archive_assets
from owl.atlas_build import build_atlas
from owl.build import build
from owl.catalog import CatalogError, capacity_plan, validate_catalog
from owl.safety import SafetyError
from owl.verify import verify_drive


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.path = self.root / 'fixture.zip'
        self.files = {
            'manual/index.html': b'<html><title>Useful manual</title><link rel="stylesheet" href="style.css"><body>Offline documentation fixture. <a href="LICENSE.txt">License</a></body></html>',
            'manual/style.css': b'body { color: black; }',
            'manual/LICENSE.txt': b'Synthetic fixture is CC0.',
            'manual/empty.txt': b'',
        }
        self.make_zip(list(self.files.items()))
        self.profile = dict(id='test', capacity_bytes=100_000_000,
                            search_budget_bytes=100_000, reserve_bytes=0)
        self.source = self.source_asset()
        self.members = [self.member(name, data, index) for index, (name, data) in enumerate(self.files.items())]

    def make_zip(self, entries):
        with warnings.catch_warnings(), ZipFile(self.path, 'w', compression=ZIP_DEFLATED) as archive:
            warnings.simplefilter('ignore', UserWarning)
            for name, data in entries:
                archive.writestr(name, data)

    def source_asset(self):
        data = self.path.read_bytes()
        return dict(id='source', title='Dependency ZIP input', category='reference', format='zip',
                    source_url=self.path.as_uri(), destination='REFERENCE/SOURCES/manual.zip',
                    version='1', size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                    license='CC0-1.0', redistributable=True, required=True, profiles=['test'],
                    supporting_file=True)

    def member(self, name, data, index):
        return {**self.source, 'id':f'member{index}', 'title': 'Useful manual' if index == 0 else f'Dependency {index}',
                'format':Path(name).suffix[1:], 'destination':'REFERENCE/' + name,
                'supporting_file':False, 'size_bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest(),
                'archive_member':dict(source_asset_id='source', path=name, document=index == 0)}

    def test_extract_pins_bytes_and_restarts_owned_partial_including_empty(self):
        with ZipSource(self.path, self.source) as archive:
            for member in self.members:
                destination = self.root / member['destination']
                part = self.root / 'staging.part'
                part.write_bytes(b'previous interrupted extraction')
                digest = archive.extract(member, destination, part=part, progress=lambda _:None)
                self.assertEqual(digest, member['sha256'])
                self.assertEqual(destination.read_bytes(), self.files[member['archive_member']['path']])
                self.assertFalse(part.exists())

    def test_source_and_output_pins_fail_without_promoting(self):
        with self.assertRaisesRegex(ArchiveError, 'SHA-256'):
            ZipSource(self.path, {**self.source, 'sha256':'0'*64})
        destination = self.root / 'output.html'
        destination.write_bytes(b'existing owned content')
        with ZipSource(self.path, self.source) as archive:
            with self.assertRaisesRegex(ArchiveError, 'SHA-256/size'):
                archive.extract({**self.members[0], 'sha256':'0'*64}, destination,
                                part=self.root/'part', progress=lambda _:None)
            changed = {**self.members[0], 'archive_member':dict(source_asset_id='source', path='missing', document=True)}
            with self.assertRaisesRegex(ArchiveError, 'missing'):
                archive.extract(changed, destination, part=self.root/'part', progress=lambda _:None)
        self.assertEqual(destination.read_bytes(), b'existing owned content')

    def test_audits_all_entries_including_unselected_unsafe_paths(self):
        cases = [
            [('safe.html', b'ok'), ('../escape', b'bad')],
            [('/absolute', b'bad')], [('a\\b', b'bad')],
            [('A/file', b'a'), ('a/other', b'b')],
            [('same', b'a'), ('same', b'b')], [('dir/', b''), ('dir/', b'')],
            [('file', b'a'), ('file/nested/', b'')],
            [('file/nested/', b''), ('file', b'a')],
        ]
        link = ZipInfo('link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases.append([(link, b'elsewhere')])
        for entries in cases:
            with self.subTest(entries=entries):
                self.make_zip(entries)
                with self.assertRaises((ArchiveError, SafetyError, ValueError)):
                    ZipSource(self.path, self.source_asset())
        self.assertFalse((self.root/'escape').exists())

    def test_archive_bomb_limits_apply_before_any_output(self):
        for constant, value in [('MAX_ARCHIVE_BYTES', 1), ('MAX_FILES', 1), ('MAX_ITEM_BYTES', 1),
                                ('MAX_EXPANDED_BYTES', 1), ('MAX_RATIO', 0)]:
            with self.subTest(limit=constant), patch('owl.archive.' + constant, value):
                with self.assertRaises(ArchiveError):
                    ZipSource(self.path, self.source)

    def test_source_mutation_and_symlink_partial_are_rejected(self):
        with ZipSource(self.path, self.source) as archive:
            sentinel = self.root/'sentinel'
            sentinel.write_bytes(b'untouched')
            part = self.root/'part'
            part.symlink_to(sentinel)
            with self.assertRaises(SafetyError):
                archive.extract(self.members[0], self.root/'out', part=part, progress=lambda _:None)
            self.assertEqual(sentinel.read_bytes(), b'untouched')
            with self.path.open('ab') as handle:
                handle.write(b'changed')
            with self.assertRaisesRegex(ArchiveError, 'changed'):
                archive.check_source()

    def test_crc_failure_and_hardlinked_partial_do_not_change_destination(self):
        # Store one file uncompressed so corrupting payload leaves the central
        # directory parseable, exercising ZipFile's CRC validation on read.
        with ZipFile(self.path, 'w') as archive:
            archive.writestr('manual/index.html', self.files['manual/index.html'])
        raw = self.path.read_bytes()
        self.path.write_bytes(raw.replace(b'Offline documentation', b'Changed documentation', 1))
        with ZipSource(self.path, self.source_asset()) as archive:
            with self.assertRaisesRegex(ArchiveError, 'Invalid ZIP member'):
                archive.extract(self.members[0], self.root/'out', part=self.root/'part', progress=lambda _:None)
        self.assertFalse((self.root/'out').exists())
        self.make_zip(list(self.files.items()))
        sentinel = self.root/'sentinel'
        sentinel.write_bytes(b'untouched')
        os.link(sentinel, self.root/'hardlink')
        with ZipSource(self.path, self.source_asset()) as archive:
            with self.assertRaises((SafetyError, RuntimeError)):
                archive.extract(self.members[0], self.root/'out', part=self.root/'hardlink', progress=lambda _:None)
        self.assertEqual(sentinel.read_bytes(), b'untouched')

    def test_directory_count_is_checked_before_zipinfo_allocation(self):
        # A false low EOCD count cannot bypass the bounded header walk.
        raw = bytearray(self.path.read_bytes())
        end = raw.rfind(b'PK\x05\x06')
        raw[end + 8:end + 12] = b'\x01\x00\x01\x00'
        self.path.write_bytes(raw)
        with patch('owl.archive.ZipFile', side_effect=AssertionError('must reject before constructor')):
            with self.assertRaisesRegex(ArchiveError, 'entry count'):
                ZipSource(self.path, self.source_asset())

    def test_prefixed_zip_is_rejected_without_executing_it(self):
        self.path.write_bytes(b'MZ' + b'\x00'*62)
        with ZipFile(self.path, 'a') as archive:
            archive.writestr('manual/index.html', b'synthetic')
        with self.assertRaisesRegex(ArchiveError, 'prefixed'):
            ZipSource(self.path, self.source_asset())

    def test_catalog_pins_and_support_accounting(self):
        assets = validate_catalog(dict(schema_version=1, assets=[*self.members, self.source]), allow_local=True)
        self.assertEqual(order_archive_assets(assets)[0]['id'], 'source')
        plan = capacity_plan(assets, self.profile)
        self.assertEqual(plan['download_bytes'], self.source['size_bytes'])
        self.assertEqual(plan['content_bytes'], self.source['size_bytes'] + sum(map(len, self.files.values())))
        self.assertEqual(plan['direct_readable_bytes'], self.members[0]['size_bytes'])
        self.assertEqual(plan['pinned_knowledge_bytes'], self.members[0]['size_bytes'])
        self.assertEqual(plan['learning_coverage']['textbooks']['count'], 0)
        for change in [dict(sha256=None), dict(source_url='https://wrong.example/archive.zip'),
                       dict(archive_member=dict(source_asset_id='unknown', path='x', document=True)),
                       dict(archive_member=dict(source_asset_id='source', path='../x', document=True))]:
            with self.subTest(change=change), self.assertRaises((CatalogError, SafetyError, ValueError)):
                validate_catalog(dict(schema_version=1, assets=[self.source, {**self.members[0], **change}]), allow_local=True)

    def test_missing_selected_source_fails_before_writes(self):
        self.source['profiles'] = []
        with self.assertRaisesRegex(CatalogError, 'select its ZIP source'):
            self.run_build(plan_only=True)
        self.assertFalse((self.root/'drive').exists())

    def test_unsupported_source_size_fails_before_download_or_writes(self):
        with patch('owl.archive.MAX_ARCHIVE_BYTES', 1), patch('owl.build.download', side_effect=AssertionError('no download')):
            with self.assertRaisesRegex(ArchiveError, 'size limits'):
                self.run_build(plan_only=True)
        self.assertFalse((self.root/'drive').exists())

    def run_build(self, **kwargs):
        profiles = self.root/'profiles'
        profiles.mkdir(exist_ok=True)
        (profiles/'test.yaml').write_text(yaml.safe_dump(self.profile))
        catalog = self.root/'library.yaml'
        catalog.write_text(yaml.safe_dump(dict(schema_version=1, assets=[*self.members, self.source])))
        return build(self.root/'drive', catalog=catalog, profiles_dir=profiles, profile_name='test',
                     allow_local=True, progress=lambda _:None, **kwargs)

    def test_build_indexes_only_documents_and_locked_rebuild_is_portable(self):
        target = self.root/'drive'
        plan = self.run_build(plan_only=True)
        self.assertFalse(target.exists())
        self.assertEqual(plan['download_bytes'], self.source['size_bytes'])
        with patch('owl.build.download', wraps=__import__('owl.build', fromlist=['download']).download) as downloader:
            result = self.run_build()
            self.assertEqual(downloader.call_count, 1)
        self.assertTrue(result['complete'])
        inventory = json.loads((target/'LIBRARY/INVENTORY.json').read_text())
        self.assertEqual(len(inventory['assets']), len(self.members) + 1)
        self.assertEqual(len(inventory['search']['assets']), 1)
        for page in ('INVENTORY.html', 'INDEX/TITLE.html'):
            if (target/'LIBRARY'/page).exists():
                text = (target/'LIBRARY'/page).read_text()
                self.assertIn('Useful manual', text)
                self.assertNotIn('Dependency', text)
        for member in self.members:
            self.assertEqual((target/'LIBRARY'/member['destination']).read_bytes(), self.files[member['archive_member']['path']])
        counts = verify_drive(target, emit=lambda _:None)
        self.assertEqual([counts[k] for k in ('MISSING', 'FAILED', 'UNKNOWN')], [0, 0, 0])
        with patch('owl.build.download', side_effect=AssertionError('unexpected download')):
            self.run_build()
        second = self.root/'second'
        build(second, catalog=target/'LIBRARY/LOCKED_CATALOG.yaml', profiles_dir=self.root/'profiles',
              profile_name='test', allow_local=True, progress=lambda _:None)
        self.assertEqual((second/'LIBRARY'/self.members[0]['destination']).read_bytes(), self.files['manual/index.html'])
        self.assertEqual(verify_drive(second, emit=lambda _:None)['FAILED'], 0)

    def test_external_cache_contains_only_zip_input(self):
        cache = self.root/'cache'
        plan = self.run_build(cache_dir=cache, plan_only=True)
        self.assertEqual(plan['remaining_cache_allocation_bytes'], self.source['size_bytes'])
        self.run_build(cache_dir=cache)
        self.assertTrue((cache/'owl-v1'/self.source['sha256']).exists())
        for member in self.members:
            self.assertFalse((cache/'owl-v1'/member['sha256']).exists())

    def test_atlas_rebuild_keeps_support_hidden_and_accepts_empty_member(self):
        self.run_build()
        nav = self.root/'navigation'
        nav.mkdir()
        topics = dict(schema_version=1, entrances=dict(subjects=['computing'], tasks=['computing'], learn=['computing']),
                      topics=[dict(id='computing', title='Computing', description='Manuals', parents=[], related=[], aliases=[])])
        (nav/'topics.yaml').write_text(yaml.safe_dump(topics))
        (nav/'assignments.yaml').write_text(yaml.safe_dump(dict(schema_version=1, assignments=[
            dict(topic_id='computing', asset_id='member0', purpose='explanation')])))
        report = build_atlas(self.root/'drive', navigation_dir=nav, catalog=self.root/'library.yaml',
                            profiles_dir=self.root/'profiles', allow_local=True, progress=lambda _:None)
        self.assertIn('INDEX/topics/computing.html', report['generated_files'])
        self.assertNotIn('Dependency', (self.root/'drive/LIBRARY/INVENTORY.html').read_text())
        inventory = json.loads((self.root/'drive/LIBRARY/INVENTORY.json').read_text())
        self.assertEqual(len(inventory['assets']), len(self.members) + 1)
        counts = verify_drive(self.root/'drive', emit=lambda _:None)
        self.assertEqual([counts[k] for k in ('MISSING', 'FAILED', 'UNKNOWN')], [0, 0, 0])


if __name__ == '__main__':
    unittest.main()
