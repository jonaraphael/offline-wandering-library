import json
import unittest

from owl.acquisition.ocw_media import freeze
from owl.safety import SafetyError


class Metadata:
    def __init__(self, missing=False, wrong=False):
        self.calls=[];self.missing=missing;self.wrong=wrong
    def fetch(self,url,kind):
        self.calls.append(url)
        return json.dumps({'metadata':{'identifier':'wrong' if self.wrong else 'course','creator':'MIT OpenCourseWare'},
            'files':[] if self.missing else [{'name':'lecture.mp4','size':'1234','md5':'a'*32,
                'sha1':'b'*40,'crc32':'c'*8,'mtime':'1','height':'720'}]}).encode()


class OcwMediaTests(unittest.TestCase):
    def inventory(self):
        return {'transformation_version':2,'content_ready':False,'source_id':'course_zip',
            'source_sha256':'d'*64,'course':{'course_title':'English Course'},'media':[{
                'source_url':'https://archive.org/download/course/lecture.mp4','id':'ocw_lecture',
                'lessons':[{'metadata_member':{'path':'resources/lesson/data.json','sha256':'e'*64,'size_bytes':10}}]}]}

    def test_shared_media_once_with_exact_pins_and_pending_readiness(self):
        metadata=Metadata()
        result=freeze([self.inventory(),self.inventory()],metadata)
        self.assertEqual(len(metadata.calls),1)
        self.assertEqual(len(result['sources']),1)
        self.assertEqual(result['budget']['download_bytes'],1234)
        self.assertEqual(result['sources'][0]['publisher_checksums']['sha1'],'b'*40)
        self.assertIsNone(result['sources'][0]['sha256'])
        self.assertFalse(result['content_ready'])

    def test_missing_media_is_not_a_buildable_capture_manifest(self):
        result=freeze([self.inventory()],Metadata(missing=True))
        self.assertNotIn('kind',result)
        self.assertEqual(len(result['exceptions']),1)
        self.assertFalse(result['content_ready'])

    def test_wrong_publisher_identity_is_rejected(self):
        with self.assertRaises(SafetyError):freeze([self.inventory()],Metadata(wrong=True))


if __name__=='__main__':unittest.main()
