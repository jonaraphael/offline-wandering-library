import hashlib
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

from owl.acquisition import ocw_runtime as runtime
from owl.safety import SafetyError


class OCWRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.before = ('/* publisher notice retained */var calls=[];var document={};'
            'function s(){calls.push("remote-youtube")}function r(){}function a(){calls.push("callback")}'
            'var t={Ts:function(){calls.push("telemetry")}};'
            + runtime.YOUTUBE + ';' + runtime.SENTRY + ';'
            'function navigation(){calls.push("navigation")}navigation();console.log(JSON.stringify(calls));').encode()
        self.pin = hashlib.sha256(self.before).hexdigest()
        self.policy = {'policy': runtime.POLICY, 'source_sha256': self.pin}

    def test_only_two_reviewed_calls_change_and_runtime_navigation_still_executes(self):
        with patch.object(runtime, 'SOURCE_SHA256', self.pin):
            output = runtime.localize_runtime(self.before, runtime.MEMBER, self.policy)
        self.assertIn(b'/* publisher notice retained */', output)
        self.assertIn(b'function navigation(){calls.push("navigation")}navigation();', output)
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is required for the actual JavaScript execution assertion')
        original = subprocess.run([node, '-e', self.before.decode()], capture_output=True, text=True, check=True)
        repaired = subprocess.run([node, '-e', output.decode()], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(original.stdout), ['remote-youtube', 'callback', 'telemetry', 'navigation'])
        self.assertEqual(json.loads(repaired.stdout), ['callback', 'navigation'])

    def test_changed_body_policy_or_member_is_rejected(self):
        with patch.object(runtime, 'SOURCE_SHA256', self.pin):
            for data, member, policy in [(self.before+b'changed', runtime.MEMBER, self.policy),
                    (self.before, 'other.js', self.policy), (self.before, runtime.MEMBER, {**self.policy, 'policy': 'arbitrary'})]:
                with self.assertRaises(SafetyError): runtime.localize_runtime(data, member, policy)

    def test_inventory_requires_the_exact_reviewed_runtime_member(self):
        with patch.object(runtime, 'SOURCE_SHA256', self.pin):
            self.assertEqual(runtime.policy_for_inventory({'members': [{'path': runtime.MEMBER, 'sha256': self.pin}]}),
                {runtime.MEMBER: self.policy})
            for members in [[], [{'path': runtime.MEMBER, 'sha256': '0'*64}]]:
                with self.assertRaises(SafetyError): runtime.policy_for_inventory({'members': members})

    def test_duplicate_startup_span_fails_closed_even_if_source_pin_were_reviewed(self):
        data=self.before+runtime.YOUTUBE.encode();pin=hashlib.sha256(data).hexdigest()
        with patch.object(runtime, 'SOURCE_SHA256', pin):
            with self.assertRaisesRegex(SafetyError, 'exact spans'):
                runtime.localize_runtime(data,runtime.MEMBER,{'policy':runtime.POLICY,'source_sha256':pin})


if __name__ == '__main__': unittest.main()
