"""Default map discovery uses the selected preset's pending recipe."""
from argparse import Namespace
from copy import deepcopy
from pathlib import Path
import unittest

from owl.acquisition.cli import _context, audit
from owl.acquisition.map_manifest import freeze_selection
from owl.acquisition.model import load_recipes
from owl.catalog import read_yaml

ROOT = Path(__file__).resolve().parents[1]


class DefaultMapRecipeTests(unittest.TestCase):
    def arguments(self, profiles):
        return Namespace(catalog=ROOT / 'catalog/library.yaml', resources=ROOT / 'catalog/resources.yaml',
            profiles_dir=ROOT / 'profiles', recipes=ROOT / 'catalog/acquisition/recipes.yaml',
            resource=['regional-maps'], profile=profiles, allow_local=False)

    def test_active_map_choices_are_finished_archives_without_topographic_placeholders(self):
        assets = read_yaml(ROOT / 'catalog/library.yaml')['assets']
        self.assertNotIn('regional_topographic_maps', {a['id'] for a in assets})
        self.assertEqual(read_yaml(ROOT / 'catalog/library.yaml').get('acquisition_recipes'), [])
        resources = {r['id']:r for r in read_yaml(ROOT / 'catalog/resources.yaml')['resources']}
        self.assertEqual(resources['regional-maps']['asset_ids'], ['map_osm_north_america'])
        self.assertIn('topographic', resources['regional-maps']['reason'])
        for identity in ('standard-512gb', 'full-1tb'):
            profile = read_yaml(ROOT / 'profiles' / (identity + '.yaml'))
            self.assertIn('world-maps', profile['default_resources'])
            self.assertNotIn('regional-maps', profile['default_resources'])

    def test_all_profile_report_can_freeze_one_profile_without_ambiguous_resource(self):
        sheet = {'sheet_id': 'one', 'scale': 24000, 'source_url': 'https://example.org/one.pdf',
                 'size_bytes': 10, 'edition': '2026', 'bbox': [0, 0, 1, 1]}
        detailed = {'resource_id': 'regional-maps', 'recipe_id': 'detailed', 'recipe_sha256': 'a' * 64,
            'inventory_complete': True, 'boundary_states': ['CT'],
            'plans': {'full-1tb': {'geographic_complete': True, 'holes': {}, 'proposed_sheets': [sheet],
                'base_scale': 24000, 'scales': [24000], 'budget_bytes': 100}}}
        coarse = deepcopy(detailed)
        coarse['recipe_id'] = 'coarse'
        coarse['plans'] = {'compact-256gb': coarse['plans'].pop('full-1tb')}
        frozen = freeze_selection({'results': [coarse, detailed]}, 'full-1tb')
        self.assertEqual(frozen['recipe_id'], 'detailed')
        self.assertFalse(frozen['content_ready'])


if __name__ == '__main__':
    unittest.main()
