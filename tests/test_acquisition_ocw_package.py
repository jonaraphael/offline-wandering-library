import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from owl.acquisition.ocw_package import inspect_package, render, portable_member_path
from owl.safety import SafetyError, validate_relative


class OCWPackageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(); self.zip = self.root/'course.zip'
        self.url = 'https://archive.org/download/official/lecture.mp4'
        self.body = '<h1>Exact context</h1><table><tr><td>42</td></tr></table><math><mi>x</mi></math>'
        video = '<video data-downloadlink="'+self.url+'"></video>'
        self.contents = {'index.html': (self.body+video+'<a href="notes.pdf">Notes</a>').encode(),
            'resources/lesson/index.html': video.encode(), 'notes.pdf': b'original PDF fixture',
            'en.vtt': b'WEBVTT\n\n00:00.000 --> 00:01.000\nComplete English transcript\n',
            'empty.js': b''}
        with ZipFile(self.zip,'w') as z:
            for name, data in self.contents.items(): z.writestr(name,data)
        self.assets = {'package': {'id':'package','size_bytes':self.zip.stat().st_size,
            'sha256':hashlib.sha256(self.zip.read_bytes()).hexdigest()}}
        self.media = self.root/'video.mp4'; self.media.write_bytes(b'original media')
        self.assets['video'] = {'id':'video','destination':'REFERENCE/COURSES/media/video.mp4',
            'size_bytes':self.media.stat().st_size,'sha256':hashlib.sha256(self.media.read_bytes()).hexdigest()}
        members=[]
        for i,(name,data) in enumerate(self.contents.items()):
            oid='output_'+str(i)
            self.assets[oid]={'id':oid,'destination':'REFERENCE/COURSES/test/'+name,'generation':{'recipe_id':'course'}}
            members.append({'path':name,'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'output_asset_id':oid})
        self.recipe={'id':'course','adapter':'ocw_package','source_asset_ids':['package','video'],
            'output_asset_ids':[m['output_asset_id'] for m in members], 'selection':{'transformation_version':1,
                'source_asset_id':'package','members':members,'media':[{'asset_id':'video','source_url':self.url,
                    'lessons':[{'context_path':'resources/lesson/index.html','captions':[{'path':'en.vtt','language':'en'}]}]}]}}
        self.sources={'package':self.zip,'video':self.media}

    def test_complete_render_preserves_documents_shared_media_and_determinism(self):
        report=inspect_package(self.recipe,self.sources,self.assets)
        self.assertFalse(report['content_ready']);self.assertEqual(report['issues'],[])
        first=render(self.recipe,self.sources,self.assets,self.root/'first')
        second=render(self.recipe,self.sources,self.assets,self.root/'second')
        self.assertEqual({i:p.read_bytes() for i,p in first.items()},{i:p.read_bytes() for i,p in second.items()})
        html=first['output_0'].read_text()
        self.assertIn(self.body,html);self.assertIn('../media/video.mp4',html)
        self.assertIn('data:text/vtt;base64,',html);self.assertIn('Complete English transcript',html)
        self.assertEqual(first['output_2'].read_bytes(),self.contents['notes.pdf'])
        self.assertEqual(first['output_4'].read_bytes(),b'')
        self.assertEqual(sum(p.name.endswith('.mp4') for p in (self.root/'first').rglob('*')),0)

    def test_inspection_never_opens_or_requires_media_bodies(self):
        self.media.unlink()
        self.assertEqual(inspect_package(self.recipe,{'package':self.zip},self.assets)['issues'],[])
        with self.assertRaises(FileNotFoundError):render(self.recipe,self.sources,self.assets,self.root/'out')

    def test_changed_member_source_collision_and_incomplete_inventory_rejected(self):
        recipe=copy.deepcopy(self.recipe);recipe['selection']['members'][0]['sha256']='0'*64
        with self.assertRaisesRegex(SafetyError,'whole-file hash'):inspect_package(recipe,self.sources,self.assets)
        recipe=copy.deepcopy(self.recipe);recipe['selection']['members'].pop();recipe['output_asset_ids'].pop()
        with self.assertRaisesRegex(SafetyError,'complete member inventory'):inspect_package(recipe,self.sources,self.assets)
        assets=copy.deepcopy(self.assets);assets['output_1']['destination']=assets['output_0']['destination']
        with self.assertRaisesRegex(SafetyError,'collide'):inspect_package(self.recipe,self.sources,assets)
        self.zip.write_bytes(self.zip.read_bytes()+b'changed')
        with self.assertRaises(SafetyError):inspect_package(self.recipe,self.sources,self.assets)

    def test_issue_blocks_writes_and_callback_never_receives_video(self):
        with patch('owl.acquisition.ocw_package.localize_html',return_value={'html':'unchanged',
                'issues':[{'kind':'unresolved-local-link','member':'missing.pdf'}]}):
            report=inspect_package(self.recipe,self.sources,self.assets)
            self.assertEqual(report['issues'][0]['document_member'],'index.html')
            self.assertEqual(report['issues'][0]['member'],'missing.pdf')
            with self.assertRaisesRegex(SafetyError,'unresolved dependencies'):
                render(self.recipe,self.sources,self.assets,self.root/'none')
        self.assertFalse((self.root/'none').exists())
        written={}
        render(self.recipe,self.sources,self.assets,self.root/'callback',output_writer=lambda p,b:written.setdefault(p,b))
        self.assertEqual(len(written),len(self.contents));self.assertNotIn(b'original media',written.values())

    def test_long_paths_map_portably_and_reproducibly(self):
        name='/'.join(['long-publisher-path'*4]*4)+'.html'
        short=portable_member_path(name)
        validate_relative('REFERENCE/COURSES/ocw_01234567890123456789/'+short)
        self.assertEqual(short,portable_member_path(name))
        self.assertNotEqual(short,portable_member_path(name+'a'))


if __name__=='__main__':unittest.main()
