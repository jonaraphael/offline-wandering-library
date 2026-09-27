"""Large metadata-only probes validate the entire input and replay offline."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from owl.acquisition.model import AcquisitionError

spec = importlib.util.spec_from_file_location("source_probe_batches", Path(__file__).resolve().parents[1] / "scripts/probe_source_batches.py")
batches = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batches)


class SourceProbeBatchTests(unittest.TestCase):
    def test_later_invalid_batch_is_rejected_before_any_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            rows = [{'id': 'map_' + str(i), 'url': 'https://example.org/' + str(i) + '.pdf'} for i in range(101)]
            rows[-1]['url'] = 'http://example.org/100.pdf'
            (root / 'requests.json').write_text(json.dumps({'schema_version': 1, 'requests': rows}))
            with patch.object(batches, 'PinProbe', side_effect=AssertionError('No HEAD before validation')):
                with self.assertRaises(AcquisitionError):
                    batches.main([str(root / 'requests.json'), '--output', str(root / 'out.json')])
            self.assertFalse((root / 'out.json').exists())

    def test_offline_replay_does_not_promote_etags_or_sizes_to_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            cache = root / 'cache' / 'head'
            cache.mkdir(parents=True)
            row = {'id': 'one', 'url': 'https://example.org/one.pdf'}
            record = {'url': row['url'], 'final_url': row['url'], 'method': 'HEAD', 'body_read': False,
                      'status': 200, 'headers': {'content-length': '10', 'etag': '"abcd-2"'}, 'checked_at': '2026-01-01'}
            (cache / (hashlib.sha256(row['url'].encode()).hexdigest() + '.json')).write_text(json.dumps(record))
            request = root / 'requests.json'
            request.write_text(json.dumps({'schema_version': 1, 'requests': [row]}))
            arguments = [str(request), '--output', str(root / 'out.json'), '--cache-dir', str(root / 'cache'), '--offline']
            with redirect_stdout(io.StringIO()), patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No network offline')):
                batches.main(arguments)
                first = (root / 'out.json').read_bytes()
                batches.main(arguments)
            self.assertEqual(first, (root / 'out.json').read_bytes())
            result = json.loads(first)
            self.assertEqual(result['body_downloads'], 0)
            self.assertEqual(result['records'][0]['size_bytes'], 10)
            self.assertIsNone(result['records'][0]['sha256'])
            self.assertEqual(result['pending_count'], 1)


if __name__ == '__main__':
    unittest.main()
