#!/usr/bin/env python3
"""Synthetic security boundary checks. No network or local history is used."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for source in ('exporters/otel/src', 'exporters/siem', 'exporters/search'):
    sys.path.insert(0, str(ROOT / source))

from agent_session_record.privacy import credential_values, redact_text
from agent_session_record.safety import private_directory, read_bounded
from asr_importer_core import META, Stream

HEADER = {'type': 'session', 'id': 'header', 'formatVersion': '0.1',
          'agent': {'name': 'com.example.agent'}, 'sessionId': 'synthetic-security',
          'producer': {'name': 'synthetic', 'version': '1', 'method': 'native'}}


class SecurityTests(unittest.TestCase):
    def test_materializing_readers_bound_bytes_and_record_counts(self):
        cases = [('asr_otel.reader', 'read_session'), ('asr_siem.reader', 'read_session'),
                 ('asr_tables.reader', 'read_stream'), ('asr_search.reader', 'read_stream'),
                 ('asr_evals.reader', 'read_session'), ('asr_telemetry_approvals.importer', 'lines')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.jsonl'
            for module_name, name in cases:
                module = importlib.import_module(module_name)
                def read():
                    result = getattr(module, name)(path, 1) if module_name == 'asr_tables.reader' else getattr(module, name)(path)
                    return list(result) if name == 'lines' else result
                with self.subTest(reader=module_name, limit='bytes'):
                    path.write_bytes(b'x' * 65)
                    with patch.object(module, 'MAX_INPUT_BYTES', 64):
                        with self.assertRaisesRegex(ValueError, 'input_capacity'):
                            read()
                with self.subTest(reader=module_name, limit='records'):
                    rows = [HEADER, *({'type': 'message', 'id': f'm-{n}', 'role': 'user', 'content': []} for n in range(3))]
                    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
                    with patch.object(module, 'MAX_RECORDS', 2):
                        with self.assertRaisesRegex(ValueError, 'input_capacity'):
                            read()

    def test_private_directories_and_bounded_descriptor_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target'
            target.mkdir(mode=0o700)
            alias = root / 'alias'
            alias.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError):
                private_directory(alias / 'child')
            self.assertFalse((target / 'child').exists())
            target.chmod(0o755)
            with self.assertRaises(ValueError):
                private_directory(target)
            source = root / 'input'
            source.write_bytes(b'x' * 65)
            with self.assertRaises(ValueError):
                read_bounded(source, 64)
            linked = root / 'linked'
            linked.symlink_to(source)
            with self.assertRaises(OSError):
                read_bounded(linked, 128)

    def test_named_credentials_are_removed_from_sibling_text_and_metadata(self):
        value = 'synthetic-private-echo'
        for item in ({'password': value, 'text': value}, json.dumps({'api_key': value, 'text': value})):
            self.assertNotIn(value, redact_text(value, credential_values(item)))
        with tempfile.TemporaryDirectory() as directory:
            stream = Stream('codex', 'synthetic-security', 'test')
            stream.header['_meta'] = {META: {'api_key': value}}
            stream.add('message', role='user', content=[{'type': 'text', 'text': value}], meta={'echo': value})
            output = Path(directory) / 'synthetic.jsonl'
            stream.write(output)
            self.assertNotIn(value, output.read_text())
            result = subprocess.run(['node', str(ROOT / 'tools/validator/bin/asr-validate.js'), '--json', str(output)],
                                    capture_output=True, check=True)
            summary = json.loads(result.stdout)
            self.assertEqual(summary['errors'], 0)
            self.assertEqual(summary['warnings'], 0)

    def test_vendor_input_and_projection_expansion_are_bounded(self):
        import asr_importer_core as core
        with patch.object(core, 'MAX_INPUT_BYTES', 8):
            with self.assertRaisesRegex(ValueError, 'input_byte_limit'):
                list(core.json_lines(b'x' * 9))
        stream = Stream('codex', 'synthetic', 'test')
        with patch.object(core, 'MAX_OUTPUT_BYTES', 8):
            with self.assertRaisesRegex(ValueError, 'output_capacity'):
                stream.add('message', role='user', content=[])
        self.assertEqual(stream.records, [])


if __name__ == '__main__':
    unittest.main()
