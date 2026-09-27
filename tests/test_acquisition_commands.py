"""The acquisition CLI forwards frozen scope and never promotes a capture."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from owl.acquisition.cli import main


class CaptureCommandTests(unittest.TestCase):
    def test_build_plan_preserves_explicit_scope_without_catalog_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = io.StringIO()
            with patch('owl.acquisition.capture.capture', return_value={
                'operation':'capture','status':'planned','content_ready':False,'body_downloads':0}) as capture, redirect_stdout(output):
                code = main(['build','--candidate-manifest',str(root/'candidates.json'),
                    '--staging-root',str(root/'staging'),'--profile','full-1tb','--resource','a,b',
                    '--plan','--cache-dir',str(root/'cache')])
            self.assertEqual(code,0)
            self.assertEqual(capture.call_args.kwargs['resource_ids'],['a','b'])
            self.assertEqual(capture.call_args.kwargs['profile'],'full-1tb')
            self.assertTrue(capture.call_args.kwargs['plan_only'])
            self.assertFalse(json.loads(output.getvalue())['content_ready'])

    def test_plan_cannot_start_a_detached_job(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(['build','--candidate-manifest','candidate.json','--staging-root','staging','--plan','--detach']),2)
