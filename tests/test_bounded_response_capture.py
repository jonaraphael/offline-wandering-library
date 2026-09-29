"""Diagnostic captures cannot silently relax exact publication source pins."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from owl.acquisition import capture as module
from owl.download import capture_bounded_response, DownloadError
from owl.safety import SafetyError


class Response(io.BytesIO):
    status = 200
    url = 'https://publisher.test/revision'

    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = headers or {'Content-Type': 'text/x-wiki', 'ETag': '"revision1"'}


class BoundedResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = {'id': 'diagnostic', 'resource_ids': ['reference'], 'source_url': Response.url,
                       'version': 'revision1 diagnostic', 'capture_mode': 'bounded-response-review',
                       'size_bytes': None, 'max_size_bytes': 64, 'sha256': None, 'publisher_checksums': {},
                       'prior_revision': {'size_bytes': 4, 'sha1': hashlib.sha1(b'old!').hexdigest()},
                       'metadata_evidence': [{'url': 'https://publisher.test/metadata', 'sha256': 'a' * 64}]}
        self.document = {'schema_version': 1, 'kind': 'acquisition', 'id': 'diagnostic', 'sources': [self.source],
                         'budget': {'download_bytes': 64, 'expanded_bytes': 0, 'preview_bytes': 0,
                                    'scratch_bytes': 0, 'cache_bytes': 0}}
        self.manifest = self.root / 'manifest.json'
        self.manifest.write_text(json.dumps(self.document))

    def test_changed_revision_is_retained_as_inadmissible_with_exact_prior(self):
        with patch('owl.download.urlopen', return_value=Response(b'new longer body')):
            result = module.capture(self.manifest, self.root / 'capture', reserve_bytes=0, progress=lambda _: None)
        receipt = json.loads((self.root / 'capture/receipts/diagnostic.json').read_text())
        self.assertEqual(receipt['status'], 'quarantined_response')
        self.assertEqual(receipt['comparison']['prior_revision'], self.source['prior_revision'])
        self.assertFalse(receipt['comparison']['sha1_matches'])
        self.assertFalse(receipt['comparison']['size_matches'])
        self.assertFalse(receipt['comparison']['admissible'])
        self.assertTrue(receipt['response_evidence']['eof'])
        self.assertEqual(receipt['size_bytes'], 15)
        self.assertEqual(json.loads(Path(result['candidate_fragment']).read_text())['assets'], [])
        with self.assertRaisesRegex(SafetyError, 'cannot be previewed'):
            module.load_capture_sources(self.root / 'capture')
        # Complete captures revalidate from local receipt with no network request.
        with patch('owl.download.urlopen', side_effect=AssertionError('unexpected network')):
            again = module.capture(self.manifest, self.root / 'capture', reserve_bytes=0, progress=lambda _: None)
        self.assertEqual(again['reused_sources'], 1)
        receipt['comparison']['sha1_matches'] = True
        (self.root / 'capture/receipts/diagnostic.json').write_text(json.dumps(receipt))
        with self.assertRaisesRegex(SafetyError, 'comparison or EOF'):
            module.capture(self.manifest, self.root / 'capture', reserve_bytes=0, progress=lambda _: None)

    def test_oversize_never_renames_or_writes_past_bound(self):
        destination = self.root / 'body'
        with patch('owl.download.urlopen', return_value=Response(b'x' * 65)):
            with self.assertRaisesRegex(DownloadError, 'enforced maximum'):
                capture_bounded_response(self.source, destination)
        self.assertFalse(destination.exists())
        self.assertLessEqual((self.root / 'body.part').stat().st_size, 64)
        with patch('owl.download.urlopen', side_effect=AssertionError('must not resume')):
            with self.assertRaisesRegex(DownloadError, 'preserve evidence'):
                capture_bounded_response(self.source, destination)

    def test_declared_length_and_partial_entities_rejected(self):
        for headers in ({'Content-Length': '65'}, {'Content-Length': '20'}, {'Content-Range': 'bytes 0-9/20'}, {'Content-Encoding': 'gzip'}):
            destination = self.root / ('body' + str(len(list(self.root.iterdir()))))
            with patch('owl.download.urlopen', return_value=Response(b'short', headers)):
                with self.assertRaises(DownloadError):
                    capture_bounded_response(self.source, destination)
            self.assertFalse(destination.exists())

    def test_limits_and_missing_prior_are_rejected(self):
        for mutation in ({'max_size_bytes': 1048577}, {'prior_revision': {'size_bytes': 4}},
                         {'size_bytes': 64}, {'fullasset_metadata': {}}, {'publisher_checksums': {'sha1': 'a' * 40}}):
            document = deepcopy(self.document)
            document['sources'][0].update(mutation)
            with self.assertRaises(SafetyError):
                module.normalize_manifest(document)
        document = deepcopy(self.document)
        document['sources'] *= 4
        with self.assertRaises(SafetyError):
            module.normalize_manifest(document)

    def test_exact_capture_does_not_accept_unknown_length_or_diagnostics(self):
        document = deepcopy(self.document)
        document['sources'][0].pop('capture_mode')
        with self.assertRaisesRegex(SafetyError, 'exact and positive'):
            module.normalize_manifest(document)
        document = deepcopy(self.document)
        document['budget']['download_bytes'] = 63
        with self.assertRaisesRegex(SafetyError, 'Download budget'):
            module.normalize_manifest(document)

    def test_revision_payload_framing_and_sha1_are_enforced(self):
        source = self.root / 'revision'
        payload = {'kind': 'mediawiki-raw-revision', 'prefix_hex': '0a0a0a0a',
                   'size_bytes': 4, 'sha1': hashlib.sha1(b'old!').hexdigest()}
        source.write_bytes(b'\n\n\n\nold!')
        self.assertEqual(module._publisher_payload(source, payload), payload)
        source.write_bytes(b'\n\n\n\nnew!')
        with self.assertRaisesRegex(SafetyError, 'publisher size or SHA1'):
            module._publisher_payload(source, payload)
        source.write_bytes(b'xxxxold!')
        with self.assertRaisesRegex(SafetyError, 'transport prefix'):
            module._publisher_payload(source, payload)
        document = deepcopy(self.document)
        row = document['sources'][0]
        row.pop('capture_mode')
        row.update(size_bytes=8, publisher_payload=payload)
        document['budget']['download_bytes'] = 8
        module.normalize_manifest(document)
        row['size_bytes'] = 9
        with self.assertRaisesRegex(SafetyError, 'transport framing'):
            module.normalize_manifest(document)

    def test_capture_never_issues_receipt_for_changed_revision_payload(self):
        body = self.root / 'wrapped-revision'
        body.write_bytes(b'\n\n\n\nnew!')
        document = deepcopy(self.document)
        source = document['sources'][0]
        source.pop('capture_mode')
        source.update(size_bytes=8, source_url=body.as_uri(),
                      publisher_payload={'kind': 'mediawiki-raw-revision', 'prefix_hex': '0a0a0a0a',
                                         'size_bytes': 4, 'sha1': hashlib.sha1(b'old!').hexdigest()})
        document['budget']['download_bytes'] = 8
        self.manifest.write_text(json.dumps(document))
        with self.assertRaisesRegex(SafetyError, 'publisher size or SHA1'):
            module.capture(self.manifest, self.root / 'changed', allow_local=True, reserve_bytes=0, progress=lambda _: None)
        self.assertFalse((self.root / 'changed/receipts/diagnostic.json').exists())
        self.assertTrue((self.root / 'changed/sources/diagnostic').exists())


if __name__ == '__main__':
    unittest.main()
