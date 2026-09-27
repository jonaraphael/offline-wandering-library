#!/usr/bin/env python3
"""Reusable real-7z QA with tiny synthetic bodies and optional local tool setup.

No library content is downloaded. --prepare-official-macos downloads only the
pinned official development tool, under ignored .owl/tools, without installing
anything globally. Ordinary reruns are offline.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import lzma
from pathlib import Path
import platform
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from owl.acquisition import sevenzip
from owl.download import download,verified
from owl.safety import SafetyError,atomic_write,reject_symlinks,sha256_file

TOOL_SOURCE={'id':'development-sevenzip-26-03-macos',
    'source_url':'https://github.com/ip7z/7zip/releases/download/26.03/7z2603-mac.tar.xz',
    'size_bytes':1863192,'sha256':'5ca87677072c59f5602e5c49baa27d4694bacd2259b4e507f0094249d4281480'}
TOOL_BINARY={'size_bytes':6069184,'sha256':'74b0910e50ea44d9760a57fada2192cfd530ba8bffbe7b47c412a464b796cabf'}
TOOL_ROOT=ROOT/'.owl/tools/sevenzip-26.03'
EXECUTABLE=None


def prepare_official_macos():
    if platform.system()!='Darwin':raise SafetyError('This pinned development bundle is for macOS only')
    reject_symlinks(TOOL_ROOT)
    owner={'owner':'owl-development-tool','tool':'7-Zip','version':'26.03'}
    marker=TOOL_ROOT/'owner.json'
    if TOOL_ROOT.exists():
        if not marker.is_file() or marker.stat().st_size>4096 or json.loads(marker.read_text())!=owner:
            raise SafetyError('Unowned development tool directory')
    else:
        TOOL_ROOT.mkdir(parents=True)
        atomic_write(marker,json.dumps(owner,sort_keys=True).encode())
    archive=TOOL_ROOT/'7z2603-mac.tar.xz'
    if not verified(archive,TOOL_SOURCE['size_bytes'],TOOL_SOURCE['sha256']):
        if archive.exists():raise SafetyError('Changed development tool archive; preserve it for inspection')
        download(TOOL_SOURCE,archive,repo_root=ROOT,retries=1,timeout=20,progress=lambda _:None)
    with lzma.open(archive,'rb') as handle:body=handle.read(32*1024*1024+1)
    if len(body)>32*1024*1024:raise SafetyError('Development bundle exceeded 32 MiB expanded bound')
    selected=set()
    with tarfile.open(fileobj=io.BytesIO(body),mode='r:') as bundle:
        for count,member in enumerate(bundle,1):
            if count>200:raise SafetyError('Development bundle exceeded 200 entries')
            if member.name not in {'7zz','License.txt','readme.txt'}:continue
            if member.name in selected or not member.isfile() or member.size>8*1024*1024:
                raise SafetyError('Unexpected development bundle member')
            selected.add(member.name)
            data=bundle.extractfile(member).read(member.size+1)
            if len(data)!=member.size:raise SafetyError('Development bundle member size differs')
            destination=TOOL_ROOT/member.name
            if destination.exists() and not verified(destination,len(data),hashlib.sha256(data).hexdigest()):
                raise SafetyError('Changed local development tool member')
            if not destination.exists():atomic_write(destination,data)
    if selected!={'7zz','License.txt','readme.txt'}:raise SafetyError('Development bundle missing executable or notices')
    executable=TOOL_ROOT/'7zz'
    if not verified(executable,TOOL_BINARY['size_bytes'],TOOL_BINARY['sha256']):raise SafetyError('Development binary pin differs')
    executable.chmod(0o700)
    return executable


def command(*arguments):
    return sevenzip._run([str(EXECUTABLE),*map(str,arguments)],limit=65536,timeout=20)


def source_record(path):
    return {'size_bytes':path.stat().st_size,'sha256':sha256_file(path)}


def archive_files(path,files,*options):
    command('a','-t7z','-mx=1','-mmt=1','-bd','-y',*options,'--',path,*files)
    return source_record(path)


class RealSevenZipChecks(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='owl-real-sevenzip-');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.payloads={'Posts.xml':b'<posts><row Id="1" Body="complete"/></posts>',
                       'Comments.xml':b'<comments><row Id="2" Text="context"/></comments>'}
        for name,data in self.payloads.items():(self.root/name).write_bytes(data)
        self.archive=self.root/'source.7z'
        self.source=archive_files(self.archive,[self.root/name for name in self.payloads])
        self.members=[{'path':name,'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                      for name,data in self.payloads.items()]
        self.addCleanup(patch.stopall)
        patch.object(sevenzip,'preflight',return_value=str(EXECUTABLE)).start()

    def test_real_listing_extract_reuse_and_observation(self):
        listing=sevenzip.inspect_archive(self.archive,self.source,max_bytes=1000,max_files=10)
        self.assertEqual({x['path'] for x in listing},set(self.payloads))
        paths=sevenzip.extract(self.archive,self.source,self.members,self.root/'strict',max_bytes=1000,max_files=10,progress=lambda _:None)
        for name,path in paths.items():self.assertEqual(path.read_bytes(),self.payloads[name])
        with patch.object(sevenzip,'_run',wraps=sevenzip._run) as run:
            sevenzip.extract(self.archive,self.source,self.members,self.root/'strict',max_bytes=1000,max_files=10,progress=lambda _:None)
        self.assertEqual(run.call_count,1)
        observed=sevenzip.observe_members(self.archive,self.source,[{k:v for k,v in m.items() if k!='sha256'} for m in self.members],
            self.root/'observed',max_bytes=1000,max_files=10,progress=lambda _:None)
        self.assertEqual(observed['members'],self.members)

    def test_real_traversal_archive_is_rejected(self):
        command('rn','-bd','-y','--',self.archive,'Posts.xml','../escape.xml')
        with self.assertRaises(SafetyError):
            sevenzip.inspect_archive(self.archive,source_record(self.archive),max_bytes=1000,max_files=10)
        self.assertFalse((self.root.parent/'escape.xml').exists())

    def test_real_limits_reject_full_inventory(self):
        for bounds in ({'max_bytes':1,'max_files':10},{'max_bytes':1000,'max_files':1}):
            with self.subTest(bounds=bounds),self.assertRaises(SafetyError):
                sevenzip.inspect_archive(self.archive,self.source,**bounds)

    def test_real_encryption_and_changed_pin_are_rejected(self):
        encrypted=self.root/'encrypted.7z'
        record=archive_files(encrypted,[self.root/'Posts.xml'],'-pfixture-only')
        with self.assertRaisesRegex(SafetyError,'Encrypted'):
            sevenzip.inspect_archive(encrypted,record,max_bytes=1000,max_files=10)
        with self.assertRaisesRegex(SafetyError,'hash/size'):
            sevenzip.extract(self.archive,self.source,[{**self.members[0],'sha256':'0'*64}],self.root/'wrong',
                max_bytes=1000,max_files=10,progress=lambda _:None)

    def test_real_write_interrupt_resumes_without_partial_promotion(self):
        destination=self.root/'interrupted'
        def interrupted(_):raise SafetyError('Synthetic live reserve failure')
        with self.assertRaisesRegex(SafetyError,'reserve failure'):
            sevenzip.extract(self.archive,self.source,self.members,destination,max_bytes=1000,max_files=10,
                progress=lambda _:None,before_write=interrupted)
        self.assertFalse((destination/'files/Posts.xml').exists())
        result=sevenzip.extract(self.archive,self.source,self.members,destination,max_bytes=1000,max_files=10,progress=lambda _:None)
        self.assertEqual(result['Posts.xml'].read_bytes(),self.payloads['Posts.xml'])

    def test_real_archive_normal_build_and_reuse(self):
        from tests.test_acquisition_build_inputs import BuildInputTests
        from owl.acquisition.runtime import Generator
        from owl.verify import verify_drive
        fixture=BuildInputTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.sevenzip_recipe()
        archive=fixture.root/'original.7z';archive.unlink()
        fixture.source.update(archive_files(archive,[fixture.original]));fixture.write()
        result=fixture.run_build()
        self.assertEqual(result['plan']['build_input_download_bytes'],archive.stat().st_size)
        self.assertEqual(verify_drive(fixture.target,emit=lambda _:None)['FAILED'],0)
        with patch('owl.build.download',side_effect=AssertionError('completed build must reuse')), \
                patch.object(Generator,'_render',side_effect=AssertionError('completed build must reuse')):
            fixture.run_build()

    def test_real_shared_xml_capture_and_two_previews(self):
        from tests.test_acquisition_stackoverflow_trial import SharedStackOverflowTests
        fixture=SharedStackOverflowTests();fixture.real_executable=EXECUTABLE
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.test_two_previews_share_one_expansion_and_review_reverifies_it()


def main(argv=None):
    global EXECUTABLE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',type=Path,default=TOOL_ROOT/'7zz')
    parser.add_argument('--prepare-official-macos',action='store_true')
    parser.add_argument('--export-evidence',type=Path)
    args=parser.parse_args(argv)
    report={'schema_version':1,'kind':'sevenzip-real-integration','passed':False,'library_bodies_downloaded':False,
            'command':'python scripts/check_sevenzip.py --export-evidence catalog/acquisition/sevenzip-real-evidence.json',
            'checker_sha256':sha256_file(Path(__file__))}
    try:
        EXECUTABLE=prepare_official_macos() if args.prepare_official_macos else args.executable.resolve()
        reject_symlinks(EXECUTABLE)
        version=command('i').decode('utf-8').splitlines()
        report.update(platform=platform.system(),architecture=platform.machine(),
            tool={'version_line':next(line.strip() for line in version if line.startswith('7-Zip')),
                  **source_record(EXECUTABLE)},
            publisher_pin={'download_page':'https://www.7-zip.org/download.html',
                'release_metadata_url':'https://api.github.com/repos/ip7z/7zip/releases/tags/26.03',
                'observed_release_metadata_sha256':'02409de2a10e7bc07d754bcdb8fc9f45ac8ce24dacb323c901e0ec96bfe56d9a',
                'observed_release_metadata_size_bytes':24564,
                'release_id':382549777,'asset_id':543966195,**TOOL_SOURCE} if verified(EXECUTABLE,TOOL_BINARY['size_bytes'],TOOL_BINARY['sha256']) else None)
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(RealSevenZipChecks)
        test_ids=[test.id().split('.')[-1] for test in suite]
        log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        report.update(passed=result.wasSuccessful(),tests_run=result.testsRun,checks=test_ids,
            failures=[test.id().split('.')[-1] for test,_ in result.failures+result.errors],
            raw_report_sha256=hashlib.sha256(log.getvalue().encode()).hexdigest(),raw_report_size_bytes=len(log.getvalue().encode()))
        if not result.wasSuccessful():print(log.getvalue()[-4096:],file=sys.stderr)
    except Exception as error:
        report['error']=type(error).__name__
        print(str(error)[-512:],file=sys.stderr)
    encoded=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
    if len(encoded)>16384:raise SafetyError('Portable integration report exceeded 16 KiB')
    if args.export_evidence:atomic_write(args.export_evidence,encoded)
    print(encoded.decode(),end='')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
