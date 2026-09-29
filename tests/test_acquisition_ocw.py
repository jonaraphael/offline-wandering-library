import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile,ZIP_DEFLATED

from owl.acquisition.ocw import package_inventory, inspect_capture
from owl.archive import ZipSource,ArchiveError,MAX_ARCHIVE_BYTES


class OcwPackageTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name).resolve()/'course.zip'

    def package(self, captions=True, unsafe=False):
        video={'uid':'lesson-1','title':'First lesson','resourcetype':'Video',
            'license':'CC-BY-NC-SA-4.0','video_files':{
                'archive_url':'http://www.archive.org/download/official/lecture.mp4',
                'video_captions_resources':[{'file':'/courses/course/en.vtt','language':'en'}]}}
        with ZipFile(self.path,'w',compression=ZIP_DEFLATED) as z:
            z.writestr('data.json',json.dumps({'course_title':'Complete course'}))
            for name in ('one','two'):
                z.writestr(f'resources/{name}/data.json',json.dumps({**video,'uid':name}))
                z.writestr(f'resources/{name}/index.html','<h1>Complete original context</h1>')
            if captions:z.writestr('static_resources/en.vtt','WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\n')
            if unsafe:z.writestr('../escape','unsafe')
        return {'id':'course','size_bytes':self.path.stat().st_size,
                'sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}

    def test_full_inventory_deduplicates_shared_video_and_preserves_contexts(self):
        asset=self.package()
        result=package_inventory(self.path,asset)
        self.assertEqual(result,package_inventory(self.path,asset))
        self.assertEqual(result['video_lesson_count'],2)
        self.assertEqual(len(result['media']),1)
        self.assertEqual(len(result['media'][0]['lessons']),2)
        self.assertEqual(result['media'][0]['source_url'],'https://archive.org/download/official/lecture.mp4')
        self.assertFalse(result['content_ready'])
        self.assertFalse(result['gaps'])
        self.assertEqual(len(result['members']),6)

    def test_missing_captions_are_gaps_and_changed_source_is_rejected(self):
        asset=self.package(captions=False)
        self.assertEqual(len(package_inventory(self.path,asset)['gaps']),2)
        with self.path.open('ab') as f:f.write(b'changed')
        with self.assertRaises(ArchiveError):package_inventory(self.path,asset)

    def test_rejects_traversal_and_preserves_small_document_limits(self):
        asset=self.package(unsafe=True)
        with self.assertRaises(ValueError):package_inventory(self.path,asset)
        asset['size_bytes']=MAX_ARCHIVE_BYTES+1
        with self.assertRaisesRegex(ArchiveError,'configured input limit'):
            ZipSource(self.path,asset)
        with self.assertRaisesRegex(ArchiveError,'at most 512'):
            ZipSource(self.path,asset,max_archive_bytes=2**30)

    def test_long_original_names_are_inspectable_without_relaxing_destinations(self):
        self.package()
        with ZipFile(self.path,'a',compression=ZIP_DEFLATED) as z:
            z.writestr('static_resources/'+'a'*125+'.vtt','WEBVTT\n')
        asset={'id':'course','size_bytes':self.path.stat().st_size,
            'sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}
        with self.assertRaises(ValueError):ZipSource(self.path,asset)
        self.assertEqual(len(package_inventory(self.path,asset)['members']),7)

    def test_explicit_isolation_keeps_bad_package_uninspected_and_finishes_next(self):
        good=self.package();bad={**good,'id':'bad-course'}
        inventory=package_inventory(self.path,good)
        output=self.path.parent/'inventories'
        def inspect(path, asset):
            if asset['id']=='bad-course':raise ArchiveError('ZIP member exceeds size/compression-ratio limits')
            return inventory
        with patch('owl.acquisition.ocw.load_manifest',return_value={'sources':[bad,good]}), \
                patch('owl.acquisition.ocw._receipt',return_value={'sha256':good['sha256'],'relative_path':'course.zip'}), \
                patch('owl.acquisition.ocw.package_inventory',side_effect=inspect):
            with self.assertRaises(ArchiveError):inspect_capture(self.path.parent,output)
            report=inspect_capture(self.path.parent,output,isolate_package_failures=True)
        self.assertEqual([r['source_id'] for r in report['courses']],['course'])
        self.assertEqual(report['failures'][0]['source_id'],'bad-course')
        self.assertEqual(report['failures'][0]['status'],'package_inventory_failed')
        self.assertFalse((output/'bad-course.json').exists())
        self.assertFalse(report['content_ready'])

    def test_receipt_failure_still_stops_isolated_inventory(self):
        good=self.package()
        with patch('owl.acquisition.ocw.load_manifest',return_value={'sources':[good]}), \
                patch('owl.acquisition.ocw._receipt',side_effect=ValueError('Captured original changed')):
            with self.assertRaisesRegex(ValueError,'original changed'):
                inspect_capture(self.path.parent,self.path.parent/'inventories',isolate_package_failures=True)


if __name__=='__main__':unittest.main()
