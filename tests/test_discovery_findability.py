"""Small production-metadata finding tasks, not a measure of answer recall."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from owl.atlas_model import load_navigation
from owl.catalog import load_catalog
from owl.discovery import compile_records

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node required for actual search runtime')
class FindingTasks(unittest.TestCase):
    def test_common_wording_and_specific_sources_reach_useful_routes(self):
        assets = load_catalog(ROOT / 'catalog/library.yaml')
        records, _ = compile_records(assets, load_navigation(ROOT / 'catalog/navigation', assets))
        # Expectations concern an available route, not factual answers or full-text recall.
        tasks = [
            ('clean water', 'topic:drinking-water'),
            ('food storage', 'topic:food-preservation'),
            ('first response', 'topic:first-aid'),
            ('finding your way', 'navigation'),
            ('human body', 'topic:anatomy'),
            ('mathematics', 'topic:mathematics'),
            ('DC circuits', 'electrical_dc'),
            ('sanitation', 'sanitation'),
            ('seed storage', 'fao_seed_storage'),
            ('soil and compost', 'fao_compost_en'),
            ('nursing skills', 'openstax_clinical_nursing_skills'),
            ('critical thinking', 'topic:philosophy'),
            ('data science', 'openstax_principles_data_science'),
            ('study skills', 'topic:college-success'),
            ('canning tomatoes', 'canning_03'),
            ('pickled foods', 'canning_06'),
            ('dental health', 'topic:dental-care'),
            ('children with visual impairments', 'topic:vision-support'),
            ('aquaponics', 'fao_aquaponics'),
            ('OpenStax Physics', 'openstax_physics'),
            ('Lessons in Electric Circuits, Volume I: DC', 'electrical_dc'),
            ('improve poor soil', 'sare_building_soils'),
            ('what to plant next year', 'sare_crop_rotation'),
            ('beneficial insects', 'sare_manage_insects'),
            ('weed control without herbicides', 'sare_manage_weeds'),
            ('green manure', 'sare_cover_crops'),
            ('build a footpath', 'usfs_trail_notebook'),
            ('clean harvested seeds', 'fao_seed_processing'),
            ('test seed germination', 'fao_seed_quality'),
            ('collect rainwater from a roof', 'cawst_rainwater'),
            ('repair an Afridev handpump', 'rwsn_afridev'),
            ('reduced borehole yield', 'sadc_groundwater_maintenance'),
            ('quantum teleportation', None),
        ]
        script = '''
const fs = require('node:fs'), api = require(process.argv[1]);
const {records, tasks} = JSON.parse(fs.readFileSync(0, 'utf8'));
const prepared = api.prepare(records);
console.log(JSON.stringify(tasks.map(([query]) => api.search(prepared, query).slice(0,5).map(x=>x.record.id))));
'''
        run = subprocess.run([shutil.which('node'), '-e', script, str(ROOT / 'src/owl/templates/search.js')],
            input=json.dumps({'records': records, 'tasks': tasks}), text=True, capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        for (query, expected), results in zip(tasks, json.loads(run.stdout)):
            with self.subTest(query=query):
                if expected is None:
                    self.assertEqual(results, [])
                else:
                    self.assertIn(expected, results)
        self.assertFalse(any(r['destination'].startswith('SOFTWARE/') for r in records))
