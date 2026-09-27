"""Exercise bounded 7z process interfaces with synthetic archive/tool fixtures."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from owl.acquisition import sevenzip
from owl.safety import SafetyError


def fixture_tool(root, payloads, *, listing=None, overflow=False, delay=0):
    executable=root/'fixture-7z'
    listing=listing if listing is not None else '\n\n'.join(
        f'Path = {name}\nSize = {len(data.encode())}\nAttributes = A\nEncrypted = -'
        for name,data in payloads.items())+'\n'
    executable.write_text('#!'+sys.executable+'\nimport sys,time\n'+
        'payloads='+repr(payloads)+'\nlisting='+repr(listing)+'\n'+
        'if sys.argv[1]=="l": print(listing)\nelse:\n'+
        f' time.sleep({delay})\n data=payloads[sys.argv[-1]].encode()\n'+
        (' data+=b"overflow"\n' if overflow else '')+' sys.stdout.buffer.write(data)\n')
    executable.chmod(0o700)
    return str(executable)


class SevenZipTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.source=self.root/'fixture.7z';self.source.write_bytes(b'7z\xbc\xaf\x27\x1c' + b'SYNTHETIC TEST FIXTURE')
        self.asset=dict(size_bytes=self.source.stat().st_size,sha256=hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.payloads={'Posts.xml':'<posts>Complete fixture</posts>','Comments.xml':'<comments>Substantive fixture</comments>'}
        self.members=[dict(path=name,size_bytes=len(data.encode()),sha256=hashlib.sha256(data.encode()).hexdigest())
                      for name,data in self.payloads.items()]
        self.tool=fixture_tool(self.root,self.payloads)
        self.output=self.root/'out'

    def extract(self,members=None,**options):
        return sevenzip.extract(self.source,self.asset,members or self.members,self.output,
            max_bytes=1000,max_files=10,progress=lambda _:None,**options)

    def test_strict_extraction_hashes_and_reuses_complete_members(self):
        with patch.object(sevenzip,'preflight',return_value=self.tool):
            result=self.extract()
            self.assertEqual(result['Posts.xml'].read_text(),self.payloads['Posts.xml'])
            with patch.object(sevenzip,'_run',wraps=sevenzip._run) as run:
                self.extract()
            self.assertEqual(run.call_count,1) # bounded listing only; no re-extraction

    def test_wrong_member_hash_and_missing_pin_are_rejected(self):
        rows=[{**self.members[0],'sha256':'0'*64}]
        with patch.object(sevenzip,'preflight',return_value=self.tool),self.assertRaisesRegex(SafetyError,'hash/size'):
            self.extract(rows)
        self.assertFalse((self.output/'files/Posts.xml').exists())
        rows=[{k:v for k,v in self.members[0].items() if k!='sha256'}]
        with patch.object(sevenzip,'preflight',return_value=self.tool),self.assertRaisesRegex(SafetyError,'requires whole-member'):
            self.extract(rows)

    def test_observation_is_explicit_and_reusable_without_approval(self):
        rows=[{k:v for k,v in m.items() if k!='sha256'} for m in self.members]
        with patch.object(sevenzip,'preflight',return_value=self.tool):
            result=sevenzip.observe_members(self.source,self.asset,rows,self.output,max_bytes=1000,max_files=10,progress=lambda _:None)
            again=sevenzip.observe_members(self.source,self.asset,rows,self.output,max_bytes=1000,max_files=10,progress=lambda _:None)
        self.assertEqual(result['members'],self.members)
        self.assertEqual(result,again)
        self.assertTrue(json.loads((self.output/'.owl-sevenzip.json').read_text())['observe_only'])

    def test_listing_rejects_traversal_case_collision_links_and_encryption(self):
        cases=['Path = ../escape\nSize = 1',
               'Path = a.xml\nSize = 1\n\nPath = A.xml\nSize = 1',
               'Path = linked\nSize = 1\nSymbolic Link = target',
               'Path = secret\nSize = 1\nEncrypted = +']
        for listing in cases:
            executable=fixture_tool(self.root,self.payloads,listing=listing)
            with self.subTest(listing=listing),patch.object(sevenzip,'preflight',return_value=executable),self.assertRaises(SafetyError):
                sevenzip.inspect_archive(self.source,self.asset,max_bytes=1000,max_files=10)

    def test_output_and_time_limits_leave_only_owned_partials(self):
        executable=fixture_tool(self.root,self.payloads,overflow=True)
        with patch.object(sevenzip,'preflight',return_value=executable),self.assertRaisesRegex(SafetyError,'byte bound'):
            self.extract([self.members[0]])
        self.assertFalse((self.output/'files/Posts.xml').exists())
        executable=fixture_tool(self.root,self.payloads,delay=2)
        with patch.object(sevenzip,'preflight',return_value=executable),self.assertRaisesRegex(SafetyError,'time limit'):
            self.extract([self.members[0]],timeout=.1)

    def test_source_hash_and_zip_interface_are_not_relaxed(self):
        self.source.write_bytes(b'PK\x03\x04not-sevenzip')
        with self.assertRaisesRegex(SafetyError,'source archive hash'):
            self.extract()
        self.asset.update(size_bytes=self.source.stat().st_size,sha256=hashlib.sha256(self.source.read_bytes()).hexdigest())
        with self.assertRaisesRegex(SafetyError,'only 7z archives'):
            self.extract()

    def test_missing_7z_is_an_explicit_dependency_failure(self):
        with patch.object(sevenzip.shutil,'which',return_value=None),self.assertRaisesRegex(SafetyError,'already installed'):
            sevenzip.preflight()

    def test_live_write_guard_stops_before_publishing_or_writing_chunk(self):
        guard=lambda size: (_ for _ in ()).throw(SafetyError('Live reserve exhausted'))
        with patch.object(sevenzip,'preflight',return_value=self.tool),self.assertRaisesRegex(SafetyError,'reserve exhausted'):
            self.extract([self.members[0]],before_write=guard)
        self.assertFalse((self.output/'files/Posts.xml').exists())
        self.assertEqual(sum(p.stat().st_size for p in (self.output/'.parts').glob('*.part')),0)


if __name__=='__main__':unittest.main()
