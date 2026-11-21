"""Compare actual desktop and browser drive builds for the same local collection."""
from base64 import b64encode
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from owl.atlas_model import load_navigation
from owl.build import build
from owl.catalog import load_catalog, load_profiles
from owl.discovery import compile_records
from owl.navigation import CSS, GROUPS, LETTERS, READING_COLLECTIONS, navigation_asset
from owl.offline_layout import layout
from owl.search_shards import ROOT, Record, compile_search_plan, encode, info, load_manifest
from owl.search_shards import packed_part, part_path, payload, read_file, script
from owl.search_ui import render_search_page


@unittest.skipUnless(shutil.which('node'), 'Node is required for browser builder parity')
class BuilderParityTests(unittest.TestCase):
    def test_demo_builds_share_content_navigation_and_search_file_trees(self):
        catalog = ROOT / 'catalog/demo.yaml'
        profiles = ROOT / 'profiles'
        navigation_dir = ROOT / 'catalog/demo-navigation'
        assets = load_catalog(catalog, load_profiles(profiles), allow_local=True)
        navigation = load_navigation(navigation_dir, assets)
        records, _ = compile_records(assets, navigation)
        nav = {key: navigation[key] for key in ('topics', 'entrances', 'assignments', 'sections', 'input_hashes')}
        nav.update(css=CSS, groups=GROUPS, letters=LETTERS, layout=layout(),
                   collections=[(key, label) for key, label, _ in READING_COLLECTIONS],
                   verify=(ROOT / 'src/owl/verify.py').read_text(encoding='utf8'),
                   assets={asset['id']: navigation_asset(asset) for asset in assets})
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            source = directory / 'source'
            source.mkdir()
            model = script('OWLShardModel', {'version': 2, 'dimensions': 256,
                                             'scales': [1] * 256, 'vocab': ['demo']})
            weights = script('OWLModelWeights', [0, b64encode(bytes(256)).decode('ascii')])
            license_text = b'MIT test fixture'
            for name, data in [('model.js', model), ('model/00.js', weights), ('model-license.txt', license_text)]:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            manifest = {'version': 1, 'model': info(model), 'license': info(license_text),
                        'model_parts': [info(weights)]}
            asset = assets[0]
            digest = asset['sha256']
            data, vectors, bloom, _ = packed_part(digest, 0, [Record('Demo library guide', '')], None)
            path = source / part_path(digest, 0)
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
            manifest['sources'] = {digest: {'records': 1, 'sha256': info(data)['sha256'],
                                             'parts': [{**info(data), 'bloom': bloom, 'vectors': vectors}]}}
            (source / 'manifest.json').write_bytes(encode(manifest))
            templates = ROOT / 'src/owl/templates'
            spec = directory / 'spec.json'
            spec.write_text(json.dumps({'assets': assets, 'navigation': nav, 'sourceRoot': str(source),
                                        'search': {'plan': compile_search_plan(assets, manifest, {}),
                                                   'base': '/search/', 'records': records, 'page': render_search_page(),
                                                   'runtime': (templates / 'search.js').read_text(encoding='utf8'),
                                                   'rankRuntime': (templates / 'rank.js').read_text(encoding='utf8')}}),
                            encoding='utf8')
            # Keep the public build entry point and inject the precomputed
            # source fixture at its manifest lookup boundary.
            with patch('owl.search_shards.load_manifest', side_effect=lambda *_: load_manifest(source)), \
                 patch('owl.search_shards.read_file', side_effect=lambda _, name, pin: read_file(source, name, pin)):
                build(directory / 'cli', catalog=catalog, profiles_dir=profiles, profile_name='demo',
                      allow_local=True, navigation_dir=navigation_dir, progress=lambda *_: None)
            completed = subprocess.run(['node', str(ROOT / 'tests/parity-build.mjs'), str(spec), str(directory / 'browser')],
                           cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            native, web = (directory / name for name in ('cli', 'browser'))
            for asset in assets:
                key = f"LIBRARY/{asset['destination']}"
                self.assertEqual((native / key).read_bytes(), (web / key).read_bytes())
            def tree(root, kind):
                return {path.relative_to(root).as_posix() for path in (root / 'LIBRARY' / kind).rglob('*') if path.is_file()}
            self.assertEqual(tree(native, 'SEARCH'), tree(web, 'SEARCH'))
            self.assertEqual(tree(native, 'INDEX'), tree(web, 'INDEX'))
            def public_paths(root):
                return {path.relative_to(root).as_posix() for path in root.rglob('*')
                        if path.is_file() and '.owl' not in path.relative_to(root).parts}
            self.assertEqual(public_paths(native) - public_paths(web),
                             {'LIBRARY/CONTENT_SELECTION.json', 'LIBRARY/LOCKED_CATALOG.yaml'})
            self.assertEqual(public_paths(web) - public_paths(native), set())
            def selection(root):
                return payload((root / 'LIBRARY/SEARCH/shards.js').read_bytes(), 'OWLShardSelection')
            self.assertEqual(selection(native), selection(web))
