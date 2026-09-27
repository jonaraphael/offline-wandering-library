import hashlib
import gzip
import io
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from owl.acquisition import mdoc
from owl.safety import SafetyError


class ManualRenderingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.raw = b'.Dd January 1, 2026\n.Dt OWL 1\n.Os\n.Sh NAME\n.Nm owl\n.Nd offline\n.Sh DESCRIPTION\n.Pp\nPreserve text.\n.Xr external 5\n'
        self.notice = b'Copyright fixture; preserve this notice.\n'
        self.fragment = b'<section><h1 id="NAME">NAME</h1><p>Preserve text. <a href="external.5.html">external(5)</a> <a href="owl.1.html">owl(1)</a></p></section>'
        self.archive = self.root / 'source.tar.gz'
        self.assets = {'source':{'size_bytes':1,'sha256':'0'*64,'destination':'REFERENCE/SOURCES/source.tar.gz'},
            'manual':{'title':'Fixture manual','format':'html','destination':'REFERENCE/MANUAL/owl.1.html'},
            'roff':{'format':'txt','destination':'REFERENCE/MANUAL/owl.1.source.txt'},
            'notice':{'format':'txt','destination':'REFERENCE/MANUAL/LICENCE.txt'}}
        self.recipe = dict(source_asset_ids=['source'],output_asset_ids=['manual','roff','notice'],selection=dict(
            source_asset_id='source',edition='Fixture 1',renderer_probe_sha256=hashlib.sha256(self.fragment).hexdigest(),
            manuals=[dict(member='release/owl.1',sha256=hashlib.sha256(self.raw).hexdigest(),
                          html_asset_id='manual',source_asset_id='roff')],
            notice=dict(member='release/LICENCE',sha256=hashlib.sha256(self.notice).hexdigest(),asset_id='notice')))
        self.write_archive()

    def write_archive(self,extra=None):
        with tarfile.open(self.archive,'w:gz') as tar:
            for name,payload in [('release/owl.1',self.raw),('release/LICENCE',self.notice),*(extra or [])]:
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                tar.addfile(member,io.BytesIO(payload))
        self.assets['source'].update(size_bytes=self.archive.stat().st_size,
                                    sha256=hashlib.sha256(self.archive.read_bytes()).hexdigest())

    def render(self):
        return mdoc.render(self.recipe,{'source':self.archive},self.assets,self.root/'output')

    def test_complete_source_notices_and_local_links_survive_deterministically(self):
        with patch.object(mdoc,'_mandoc',return_value=self.fragment):
            result=self.render()
            first=result['manual'].read_bytes()
            self.assertEqual(first,self.render()['manual'].read_bytes())
        self.assertEqual(result['roff'].read_bytes(),self.raw)
        self.assertEqual(result['notice'].read_bytes(),self.notice)
        page=first.decode()
        self.assertIn('href="owl.1.html"',page)
        self.assertNotIn('href="external.5.html"',page)
        self.assertIn('external.5',page)
        self.assertIn('Original roff and per-file notices',page)

    def test_changed_source_rejected(self):
        self.archive.write_bytes(self.archive.read_bytes()+b'changed')
        with patch.object(mdoc,'_mandoc',return_value=self.fragment),self.assertRaisesRegex(SafetyError,'hash/size'):
            self.render()

    def test_tar_traversal_and_duplicate_rejected(self):
        for extra in [[('../escape',b'x')],[('release/owl.1',self.raw)]]:
            self.write_archive(extra)
            with patch.object(mdoc,'_mandoc',return_value=self.fragment),self.assertRaisesRegex(SafetyError,'Unsafe'):
                self.render()

    def test_pax_and_gnu_metadata_are_bounded_before_tarfile_parses_them(self):
        # These extension headers are consumed inside tarfile before a member
        # is yielded, so per-member file-size checks cannot protect the parser.
        for typeflag in (tarfile.XHDTYPE, tarfile.GNUTYPE_LONGNAME):
            with self.subTest(typeflag=typeflag):
                header=tarfile.TarInfo('extension')
                header.type=typeflag
                header.size=32768
                self.archive.write_bytes(gzip.compress(header.tobuf()+b'x'*32768+b'\0'*1024))
                self.assets['source'].update(size_bytes=self.archive.stat().st_size,
                    sha256=hashlib.sha256(self.archive.read_bytes()).hexdigest())
                with patch.object(mdoc,'_mandoc',return_value=self.fragment), \
                        patch.object(mdoc,'MAX_ARCHIVE_BYTES',16384), \
                        self.assertRaisesRegex(SafetyError,'decompressed-byte bound'):
                    self.render()
                self.assertFalse((self.root/'output').exists())

    def test_archive_wrapper_never_requests_or_returns_unbounded_data(self):
        source=io.BytesIO(b'x'*4096)
        with patch.object(mdoc,'MAX_ARCHIVE_BYTES',1024):
            bounded=mdoc._BoundedArchive(source)
            with self.assertRaisesRegex(SafetyError,'Unbounded'):
                bounded.read()
            with self.assertRaisesRegex(SafetyError,'decompressed-byte bound'):
                bounded.read(10**12)
            self.assertEqual(source.tell(),1025)

    def test_source_includes_rejected_before_render(self):
        self.raw += b'.so /etc/passwd\n'
        self.recipe['selection']['manuals'][0]['sha256']=hashlib.sha256(self.raw).hexdigest()
        self.write_archive()
        with patch.object(mdoc,'_mandoc',return_value=self.fragment),self.assertRaisesRegex(SafetyError,'external-file'):
            self.render()

    def test_wrong_member_pin_rejected(self):
        self.recipe['selection']['manuals'][0]['sha256']='0'*64
        with patch.object(mdoc,'_mandoc',return_value=self.fragment),self.assertRaisesRegex(SafetyError,'member hash'):
            self.render()

    def test_missing_dependency_and_changed_renderer_rejected(self):
        with patch.object(mdoc.shutil,'which',return_value=None),self.assertRaisesRegex(SafetyError,'mandoc on PATH'):
            mdoc.preflight(self.recipe)
        with patch.object(mdoc,'_mandoc',return_value=b'changed'),self.assertRaisesRegex(SafetyError,'renderer differs'):
            mdoc.preflight(self.recipe)

    def test_duplicate_outputs_rejected(self):
        self.recipe['selection']['manuals'][0]['source_asset_id']='manual'
        with patch.object(mdoc,'_mandoc',return_value=self.fragment),self.assertRaisesRegex(SafetyError,'output IDs'):
            self.render()

    def test_renderer_output_and_diagnostics_are_bounded(self):
        program=self.root/'fixture-renderer'
        program.write_text('#!'+sys.executable+'\nimport sys\nsys.stdout.write("x" * 65536)\n')
        program.chmod(0o700)
        with patch.object(mdoc.shutil,'which',return_value=str(program)),patch.object(mdoc,'MAX_OUTPUT',1024),self.assertRaisesRegex(SafetyError,'bounded output'):
            mdoc._mandoc(self.raw,'Fixture 1')

    def test_section_links_require_existing_targets_and_exact_counts(self):
        self.recipe['selection']['manuals'][0]['section_links']={'#OLD':{'target':'owl.1.html#NAME','expected_count':1}}
        with patch.object(mdoc,'_mandoc',return_value=self.fragment),self.assertRaisesRegex(SafetyError,'occurrence count'):
            self.render()
        self.recipe['selection']['manuals'][0]['section_links']['#OLD']['target']='owl.1.html#ABSENT'
        with patch.object(mdoc,'_mandoc',return_value=self.fragment),self.assertRaisesRegex(SafetyError,'missing pinned target'):
            self.render()

    @unittest.skipUnless(shutil.which('mandoc'),'mandoc is an optional build-time dependency')
    def test_real_mandoc_preserves_text_without_network(self):
        self.recipe['selection']['renderer_probe_sha256']=hashlib.sha256(mdoc._mandoc(mdoc.PROBE,'Fixture 1')).hexdigest()
        page=self.render()['manual'].read_text()
        self.assertIn('Preserve text.',page)
        self.assertIn('external.5',page)
        self.assertNotIn('href="external.5.html"',page)


if __name__=='__main__': unittest.main()
