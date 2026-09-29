import importlib.util
from pathlib import Path
import unittest

from owl.safety import SafetyError

MODULE=Path(__file__).resolve().parents[1]/'scripts/check_manual_package.py'
spec=importlib.util.spec_from_file_location('manual_package_browser',MODULE)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class BrowserPackageTests(unittest.TestCase):
    def test_complete_bounded_deterministic_shards(self):
        assets=[{'id':f'p{i:03d}','destination':f'manual/{i}.html','format':'html','generation':{'recipe_id':'fixed'}} for i in range(201)]
        fragment={'assets':assets[::-1]+[{'id':'image','format':'png'}]}
        shards=module.plan(fragment)
        self.assertEqual([len(s) for s in shards],[75,75,51])
        self.assertEqual([r for shard in shards for r in shard],assets)
        with self.assertRaises(SafetyError):module.plan(fragment,batch_size=101)
        with self.assertRaises(SafetyError):module.plan({'assets':[assets[0],assets[0]]})
        with self.assertRaises(SafetyError):module.plan({'assets':[]})
        notice={'id':'notice','destination':'notices/license.html','format':'html','supporting_file':True}
        with_notice={'assets':[assets[0],notice],'recipes':[{'selection':{'dependencies':{'notices/license.html':'notice'}}}]}
        self.assertEqual(sum(map(len,module.plan(with_notice))),2)

    def test_resume_validates_shared_dependencies_and_report_pins(self):
        import argparse
        import hashlib
        import json
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();files=root/'files';files.mkdir();out=root/'reports'
            assets=[]
            for filename,data,fmt in [('page.html',b'page','html'),('theme.css',b'old theme','css')]:
                (files/filename).write_bytes(data)
                assets.append({'id':filename,'destination':filename,'format':fmt,'generation':{'recipe_id':'fixed'},
                    'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            fragment=root/'fragment.json';fragment.write_text(json.dumps({'assets':assets}))
            args=argparse.Namespace(fragment=fragment,root=files,output=out,batch_size=75,node='node',browser='chrome',playwright='playwright')
            calls=[]
            def process(command,**kwargs):
                if '--version' in command:return SimpleNamespace(stdout='Pinned browser',returncode=0)
                calls.append(command)
                result={'checks':2,'passed':2,'results':[{'asset_id':'page.html','width':w,'passed':True} for w in [1280,390]]}
                Path(command[command.index('--output')+1]).write_text(json.dumps(result))
                return SimpleNamespace(returncode=0)
            with patch.object(module.subprocess,'run',side_effect=process):
                self.assertEqual(module.run(args)['shards_reused'],0)
                self.assertEqual(module.run(args)['shards_reused'],1)
                (files/'theme.css').write_bytes(b'new theme')
                with self.assertRaisesRegex(SafetyError,'source changed'):module.run(args)
                assets[1]['sha256']=hashlib.sha256(b'new theme').hexdigest()
                fragment.write_text(json.dumps({'assets':assets}))
                self.assertEqual(module.run(args)['shards_reused'],0)
                self.assertEqual(len(calls),2)
