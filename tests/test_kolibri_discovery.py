import copy
import importlib.util
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('kolibri_discovery', Path(__file__).resolve().parents[1] / 'scripts/discover_kolibri.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Metadata:
    def __init__(self, responses):
        self.responses = responses
        self.evidence = []
    def fetch(self, url, **kwargs):
        return json.dumps(self.responses.pop(0)).encode()


class KolibriDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.channel = {'id': 'a'*32, 'version': 5, 'last_published': '2026-01-01', 'lang_code': 'en',
                        'resource_id': 'khan-core-stem', 'courses': [{'id': 'b'*32, 'title': 'Arithmetic', 'lft': 1, 'rght': 4}]}
        self.selection = {'channels': [self.channel], 'limits': {'requests': 10, 'metadata_bytes': 100000, 'nodes': 10, 'files': 10}}
        self.node = {'id': 'c'*32, 'content_id': 'd'*32, 'channel_id': 'a'*32, 'title': 'Count',
                     'kind': 'exercise', 'lft': 2, 'rght': 3, 'lang': {'lang_code': 'en'},
                     'license_name': 'Special Permissions', 'license_description': 'Through Kolibri only',
                     'files': [{'id': 'e'*32, 'checksum': 'f'*32, 'extension': 'perseus', 'file_size': 123,
                                'storage_url': '/content/storage/f/f/'+'f'*32+'.perseus', 'available': True,
                                'priority': 1, 'preset': 'exercise', 'thumbnail': False, 'supplementary': False}]}
    def discover(self, page, channel=None):
        return MODULE.discover(self.selection, Metadata([channel or self.channel, page]))
    def test_inventory_is_pending_and_permission_scope_explicit(self):
        result = self.discover({'results': [self.node], 'more': None})
        self.assertFalse(result['content_ready'])
        self.assertEqual(result['download_bytes'], 123)
        self.assertEqual(result['issues'][0]['kind'], 'publisher_permission_scope_review')
    def test_missing_descendants_remain_explicit(self):
        result = self.discover({'results': [], 'more': None})
        self.assertEqual(result['issues'][0]['kind'], 'incomplete_course_inventory')
    def test_changed_published_version_rejected(self):
        with self.assertRaisesRegex(ValueError, 'revision'):
            self.discover({}, dict(self.channel, version=6))
    def test_pagination_cannot_escape_subject_scope(self):
        with self.assertRaisesRegex(ValueError, 'scope'):
            self.discover({'results': [], 'more': {'channel_id': 'a'*32, 'descendant_of': '0'*32, 'max_results': '250'}})
    def test_duplicate_nodes_and_file_path_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.discover({'results': [self.node, self.node], 'more': None})
        node = copy.deepcopy(self.node)
        node['files'][0]['storage_url'] = 'https://other.example/lesson.perseus'
        with self.assertRaisesRegex(ValueError, 'file identity'):
            self.discover({'results': [node], 'more': None})
    def test_one_video_rendition_and_english_captions(self):
        def file(preset, ext, sha, **extra):
            return {'preset': preset, 'extension': ext, 'checksum': sha, 'priority': 1,
                    'supplementary': False, 'thumbnail': False, **extra}
        node = {'kind': 'video', 'files': [file('low_res_video', 'mp4', 'a'),
            file('high_res_video', 'mp4', 'b'), file('video_subtitle', 'vtt', 'c', supplementary=True, lang={'lang_code': 'en'}),
            file('video_subtitle', 'vtt', 'd', supplementary=True, lang={'lang_code': 'es'})]}
        self.assertEqual([f['checksum'] for f in MODULE.choose_files(node)], ['b', 'c'])

    def test_exercise_census_is_deterministic_deduplicated_and_pending(self):
        inventory = self.discover({'results': [self.node], 'more': None})
        inventory['nodes'][0]['owl_metadata_evidence'] = {'url':'https://example.org/metadata','sha256':'a'*64}
        inventory['works'].append({**inventory['works'][0], 'id':'1'*32})
        frozen = MODULE.freeze_exercises(inventory, 'a'*64)
        self.assertFalse(frozen['content_ready'])
        self.assertEqual(len(frozen['sources']), 1)
        self.assertEqual(frozen['budget']['download_bytes'], 123)
        self.assertEqual(len(frozen['sources'][0]['work_ids']), 2)
        inventory['works'].reverse()
        self.assertEqual(frozen, MODULE.freeze_exercises(inventory, 'a'*64))
        inventory['works'][0]['file_ids'] = []
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            MODULE.freeze_exercises(inventory, 'a'*64)


if __name__ == '__main__':
    unittest.main()
