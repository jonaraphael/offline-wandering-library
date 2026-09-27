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

    def test_full_default_audit_uses_identical_detailed_recipe_without_active_outputs(self):
        args = self.arguments(['full-1tb'])
        context = _context(args)
        recipes = context[-1]
        expected = load_recipes(ROOT / 'catalog/acquisition/regional-maps-detailed-1tb.yaml')
        self.assertEqual(recipes, expected)
        self.assertEqual(set(recipes), {'regional-maps-detailed-1tb-v1'})
        row = next(iter(recipes.values()))
        self.assertEqual(row['selection']['allowances'], {'full-1tb': 80_000_000_000})
        self.assertEqual(row['review']['status'], 'pending')
        self.assertEqual(row['output_asset_ids'], [])
        self.assertEqual([r['id'] for r in audit(args, context)['gaps'][0]['recipes']], list(recipes))
        active = read_yaml(args.catalog).get('acquisition_recipes', [])
        self.assertNotIn(row['id'], {r['id'] for r in active})

    def test_smaller_presets_keep_coarse_recipe_and_allowances(self):
        for profile in ('compact-256gb', 'standard-512gb'):
            with self.subTest(profile=profile):
                recipes = _context(self.arguments([profile]))[-1]
                self.assertEqual(set(recipes), {'regional-maps-acquisition-v2'})
                self.assertEqual(next(iter(recipes.values()))['selection']['allowances'],
                                 {'compact-256gb': 10_000_000_000, 'standard-512gb': 30_000_000_000})

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
