"""Content readiness must not claim, or depend on, physical certification."""
from pathlib import Path
import tempfile
import unittest
import yaml

from owl.catalog import CatalogError
from owl.resources import load_resources, resolve_resources


class ContentReadinessTests(unittest.TestCase):
    def test_ready_content_can_have_pending_device_certification(self):
        asset = {'id':'manual','status':'resolved','size_bytes':10,'format':'txt',
                 'destination':'BOOKS/manual.txt','profiles':[]}
        resource = {'id':'manuals','title':'Manuals','status':'ready','asset_ids':['manual'],
            'target_bytes':10,'device_validation':{'status':'pending','reason':'Physical device not tested','evidence':[]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resources.yaml'
            path.write_text(yaml.safe_dump({'schema_version':1,'resources':[resource]}))
            resources = load_resources(path,[asset])
            selection = resolve_resources([asset],{'id':'test','default_resources':['manuals']},resources)
            self.assertEqual(selection['incomplete_resources'],[])
            self.assertEqual(selection['resource_rows'][0]['device_validation']['status'],'pending')
            resource['device_validation']['status']='passed'
            path.write_text(yaml.safe_dump({'schema_version':1,'resources':[resource]}))
            with self.assertRaisesRegex(CatalogError,'requires evidence'):
                load_resources(path,[asset])
