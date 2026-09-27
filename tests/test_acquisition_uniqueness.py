"""Optional expansion editions cannot recount a selected work or archive entry."""
from copy import deepcopy
import unittest

from owl.acquisition.runtime import selected_recipes
from owl.catalog import CatalogError


class SelectionUniquenessTests(unittest.TestCase):
    def records(self, adapter='html_snapshot'):
        source = {'id':'source','sha256':'a'*64}
        recipes = {key:{'id':key,'adapter':adapter,'source_asset_ids':['source'],
            'output_asset_ids':[key+'-output'],'selection':{'work_ids':['gutenberg:123']}}
            for key in ['baseline','additional']}
        assets = [source]+[{'id':key+'-output','generation':{'recipe_id':key}} for key in recipes]
        return assets, recipes

    def test_whole_work_duplicates_fail_only_when_both_editions_are_selected(self):
        assets, recipes = self.records()
        with self.assertRaisesRegex(CatalogError,'Duplicate selected work'):
            selected_recipes(assets,recipes)
        self.assertEqual(set(selected_recipes(assets[:2],recipes)),{'baseline'})

    def test_archive_entry_duplicates_are_bound_to_the_source_pin(self):
        assets, recipes = self.records('zim_direct')
        for recipe in recipes.values():
            recipe['selection']={'source_asset_id':'source','entries':['A/Complete_work']}
        with self.assertRaisesRegex(CatalogError,'Duplicate selected work'):
            selected_recipes(assets,recipes)
        recipes['additional']['selection']['entries']=['A/Another_work']
        self.assertEqual(len(selected_recipes(assets,recipes)),2)
