import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from corpus_source import identity, partition

ROOT = Path(__file__).resolve().parents[3]


def write(path, *records):
    path.write_text(''.join(json.dumps(value) + '\n' for value in records))


def meta(session):
    return {'type': 'session_meta', 'payload': {'id': session}}


class CorpusTests(unittest.TestCase):
    def test_partition_keeps_complete_identities_and_unidentified_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write(directory/'a.jsonl', meta('shared'))
            write(directory/'b.jsonl', meta('shared'))
            write(directory/'c.jsonl', meta('other'))
            write(directory/'unknown.jsonl', {'type': 'unknown'})
            chunks = partition('codex', directory, ['a.jsonl', 'b.jsonl', 'c.jsonl', 'unknown.jsonl'], 1)
            self.assertEqual(chunks, [['a.jsonl', 'b.jsonl', 'unknown.jsonl'], ['c.jsonl']])

    def test_thread_identity_uses_recorded_ids_and_native_filename_corroboration(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root = '00000000-0000-4000-8000-000000000000'
            child = '00000000-0000-4000-8000-000000000001'
            own = meta(child)
            own['payload']['session_id'] = root
            native = directory/f'rollout-2026-10-31T12-00-00-{child}.jsonl'
            write(native, meta(root), own, meta(root))
            self.assertEqual(identity('codex', native), child)
            ambiguous = directory/'ambiguous.jsonl'
            write(ambiguous, meta(root), own)
            self.assertIsNone(identity('codex', ambiguous))
            write(ambiguous, own)
            self.assertEqual(identity('codex', ambiguous), child)
            write(ambiguous, {'type': 'session_meta', 'payload': {'session_id': root}})
            self.assertIsNone(identity('codex', ambiguous))

    @unittest.skipUnless(shutil.which('zstd'), 'optional compressed discovery command is absent')
    def test_compressed_companions_share_recorded_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            native = directory/'native.jsonl'
            write(native, meta('compressed'))
            compressed = directory/'native.jsonl.zst'
            compressed.write_bytes(subprocess.check_output(['zstd', '-q', '-c', '--', str(native)]))
            self.assertEqual(identity('codex', compressed), 'compressed')
            self.assertEqual(partition('codex', directory, [native.name, compressed.name], 1), [[native.name, compressed.name]])

    def test_parallel_harness_pairs_calls_across_files_and_resumes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)/'native'
            directory.mkdir()
            write(directory/'a.jsonl', meta('shared'), {'type': 'response_item', 'payload': {'type': 'function_call', 'id': 'native-call', 'call_id': 'run', 'name': 'exec_command', 'arguments': '{}'}})
            write(directory/'b.jsonl', meta('shared'), {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'run', 'output': 'done'}})
            write(directory/'c.jsonl', meta('second'))
            write(directory/'d.jsonl', meta('third'))
            write(directory/'unknown.jsonl', {'type': 'unknown'})
            out = Path(temporary)/'out'
            command = ['python3', str(Path(__file__).with_name('check-corpus.py')), '--binary', str(ROOT/'target/debug/asr'), '--validator', str(ROOT/'tools/validator/bin/asr-validate.js'), '--out', str(out), '--jobs', '2', '--max-files-per-batch', '1', '--root', f'codex={directory}']
            first = subprocess.run(command, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr.decode())
            summary = json.loads((out/'summary.json').read_text())
            self.assertEqual(summary['batches'], 3)
            self.assertEqual(summary['failed_batches'], 0)
            self.assertEqual(summary['by_agent']['codex']['native_files'], 5)
            self.assertEqual(summary['by_agent']['codex']['files'], 3)
            self.assertEqual(summary['validation_codes'].get('warning:call-without-result', 0), 0)
            self.assertEqual(summary['conversion_codes']['unidentified_source'], 1)
            before = (out/'counts.json').read_bytes()
            second = subprocess.run(command, capture_output=True)
            self.assertEqual(second.returncode, 0, second.stderr.decode())
            self.assertEqual((out/'counts.json').read_bytes(), before)

    def test_unidentified_only_batch_retains_conversion_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)/'native'
            directory.mkdir()
            write(directory/'unknown.jsonl', {'type': 'unknown'})
            out = Path(temporary)/'out'
            command = ['python3', str(Path(__file__).with_name('check-corpus.py')), '--binary', str(ROOT/'target/debug/asr'), '--validator', str(ROOT/'tools/validator/bin/asr-validate.js'), '--out', str(out), '--root', f'codex={directory}']
            checked = subprocess.run(command, capture_output=True)
            self.assertEqual(checked.returncode, 1, checked.stderr.decode())
            summary = json.loads((out/'summary.json').read_text())
            self.assertEqual(summary['failed_batches'], 1)
            self.assertEqual(summary['by_agent']['codex']['conversion_files'], 1)
            self.assertEqual(summary['by_agent']['codex']['conversion_sessions'], 0)
            self.assertEqual(summary['conversion_codes'], {'unidentified_source': 1})
            self.assertEqual(list(out.rglob('*.jsonl')), [])


if __name__ == '__main__':
    unittest.main()
