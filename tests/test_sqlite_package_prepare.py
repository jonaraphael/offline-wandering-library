import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from owl.safety import SafetyError

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/prepare_sqlite_package.py'
spec=importlib.util.spec_from_file_location('sqlite_package_prepare',SCRIPT)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class SQLitePreparationTests(unittest.TestCase):
    def test_complete_capture_preparation_is_reproducible_and_source_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();source=root/'package.zip';body=b'<img src="https://publisher.test/art.gif"><p>Complete text</p>'
            with ZipFile(source,'w') as z:z.writestr('manual/guide.html',body)
            companion=root/'art.gif';companion.write_bytes(b'GIF89a fixture')
            def pin(path):return hashlib.sha256(path.read_bytes()).hexdigest()
            def write(name,value):
                path=root/name;path.write_text(json.dumps(value));return path
            member={'id':'guide','destination':'REFERENCE/manual/guide.html','format':'html','version':'1','size_bytes':len(body),
                'sha256':hashlib.sha256(body).hexdigest(),'archive_member':{'source_asset_id':'source','path':'manual/guide.html'}}
            sources=[{'id':'source','fullasset_metadata':{'id':'source','destination':'REFERENCE/source.zip','size_bytes':source.stat().st_size,'sha256':pin(source),'version':'1'}},
                {'id':'art','fullasset_metadata':{'id':'art','destination':'REFERENCE/manual/art.gif','size_bytes':companion.stat().st_size,'sha256':pin(companion),'supporting_file':True}}]
            receipts=[{'source_id':'source','relative_path':'package.zip','sha256':pin(source)},{'source_id':'art','relative_path':'art.gif','sha256':pin(companion)}]
            audit=write('audit.json',{'original':'reviewed fixture'})
            policy={'schema_version':1,'id':'fixture-sqlite','source_id':'source','source_sha256':pin(source),'original_audit_sha256':pin(audit),
                'dependencies':{'manual/art.gif':'art'},'repairs':[{'member':'manual/guide.html','original_sha256':member['sha256'],'attribute':'src','from':'https://publisher.test/art.gif','target_member':'manual/art.gif','expected_count':1}],
                'optional_historical_reference':{}}
            args=argparse.Namespace(staging=root,policy=write('policy.json',policy),source_audit=audit,members=write('members.json',{'assets':[member]}),output=root/'proposal.json')
            with patch.object(module,'load_capture_sources',return_value=({'sources':sources},receipts)):
                first=module.prepare(args);frozen=args.output.read_bytes();self.assertEqual(module.prepare(args),first);self.assertEqual(args.output.read_bytes(),frozen)
                proposal=json.loads(frozen);output=next(a for a in proposal['assets'] if a.get('generation'))
                self.assertEqual(output['sha256'],hashlib.sha256(body.replace(b'https://publisher.test/art.gif',b'art.gif')).hexdigest())
                self.assertFalse(proposal['content_ready'])
                policy['repairs'][0]['original_sha256']='0'*64;write('policy.json',policy)
                with self.assertRaisesRegex(SafetyError,'source-member hash changed'):module.prepare(args)
