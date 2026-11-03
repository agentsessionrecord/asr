"""Performance evidence must measure children separately and compare exact bytes."""
from pathlib import Path
import sys
import tempfile
import unittest

from performance_corpus import compare, digest, measured, same_bytes, status, summary


class PerformanceTests(unittest.TestCase):
    def test_exact_comparison_checks_names_and_full_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root/'actual'
            expected = root/'reference'/'agent-001'/'asr'
            actual.mkdir()
            expected.mkdir(parents=True)
            self.assertEqual(compare(actual, [root/'reference'], 'agent-001'), 'output_missing')
            a = actual/'session.jsonl'
            b = expected/'session.jsonl'
            # The differing byte is beyond the first comparison buffer.
            a.write_bytes(b'x' * (1024 * 1024) + b'\n')
            b.write_bytes(a.read_bytes())
            self.assertTrue(same_bytes(a, b))
            self.assertEqual(compare(actual, [root/'reference'], 'agent-001'), 'equal')
            self.assertEqual(digest(a), digest(b))
            b.write_bytes(b'x' * (1024 * 1024) + b'!')
            self.assertEqual(compare(actual, [root/'reference'], 'agent-001'), 'bytes_changed')
            b.rename(expected/'other.jsonl')
            self.assertEqual(compare(actual, [root/'reference'], 'agent-001'), 'file_set_changed')
            self.assertEqual(compare(actual, [root/'missing'], 'agent-001'), 'reference_missing')

    @unittest.skipUnless(sys.platform == 'linux' and Path('/usr/bin/time').exists(), 'GNU time required')
    def test_child_measurements_and_phase_aggregation(self):
        code = ('import json, sys; print("summary"); '
                'print(json.dumps({"phase":"projection","seconds":.25}),file=sys.stderr); '
                'print(json.dumps({"phase":"projection","seconds":.5}),file=sys.stderr)')
        result, output = measured([sys.executable, '-c', code], 10, profile=True)
        self.assertEqual(result['exit'], 0)
        self.assertEqual(output, b'summary\n')
        self.assertGreater(result['peak_rss_kib'], 0)
        self.assertGreater(result['seconds'], 0)
        self.assertEqual(result['phases'], {'projection': .75})
        result, _ = measured([sys.executable, '-c', 'raise SystemExit(7)'], 10)
        self.assertEqual(result['exit'], 7)

    @unittest.skipUnless(sys.platform == 'linux' and Path('/usr/bin/time').exists(), 'GNU time required')
    def test_deadline_reaps_owned_process_group(self):
        # The grandchild inherits the pipes. communicate would hang if only
        # the GNU time wrapper or its immediate child were stopped.
        code = ('import subprocess, sys, time; '
                'subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                'time.sleep(30)')
        result, output = measured([sys.executable, '-c', code], .2)
        self.assertIsNone(result['exit'])
        self.assertLess(result['seconds'], 5)
        self.assertEqual(output, b'')

    def test_summary_keeps_timeout_and_diagnostic_evidence(self):
        result = summary({
            'a': {'agent': 'codex', 'status': 'passed',
                  'measurement': {'seconds': 1, 'peak_rss_kib': 1024},
                  'conversion': {'diagnostics': {'secret_redacted': 2}},
                  'validation': {'records': 4, 'errors': 0, 'warnings': 1,
                                 'counts': {'warning:unknown-type': 1}}},
            'b': {'agent': 'codex', 'status': 'conversion_timeout',
                  'measurement': {'seconds': 120}},
        })
        agent = result['by_agent']['codex']
        self.assertEqual(result['workers'], 1)
        self.assertEqual(agent['files'], 2)
        self.assertEqual(agent['seconds']['max'], 120)
        self.assertEqual(agent['statuses']['conversion_timeout'], 1)
        self.assertEqual(agent['conversion_codes'], {'secret_redacted': 2})
        self.assertEqual(agent['validation_codes'], {'warning:unknown-type': 1})

    def test_incomplete_evidence_cannot_pass_a_comparison_recheck(self):
        result = {'source_unchanged': True, 'validation_measurement': {'exit': 0},
                  'measurement': {'seconds': 1}, 'comparison': 'equal'}
        self.assertEqual(status(result, 120), 'validation_failed')
        result['validation_measurement']['exit'] = None
        self.assertEqual(status(result, 120), 'validation_timeout')
        result['validation_measurement']['exit'] = 0
        result['validation'] = {'valid': True, 'errors': 0, 'inputFailures': 0}
        self.assertEqual(status(result, 120), 'passed')
        result['comparison'] = 'reference_missing'
        self.assertEqual(status(result, 120), 'reference_missing')


if __name__ == '__main__':
    unittest.main()
