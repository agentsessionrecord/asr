import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from database_corpus import catalog, check_file, summarize


class DatabaseTests(unittest.TestCase):
    def test_catalog_handles_database_aliases_and_native_migration_precedence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'agent').mkdir()
            native = root/'agent/openclaw-agent.sqlite'
            native.touch()
            (root/'sessions').mkdir()
            (root/'sessions/old.jsonl').touch()
            (root/'alias.db').symlink_to(native)
            value = catalog([f'openclaw={root}'], 100)
            self.assertEqual(len(value['files']), 1)
            self.assertEqual(value['inventory']['openclaw']['migration_companions'], 1)
            self.assertEqual(value['inventory']['openclaw']['file_aliases'], 1)
            self.assertEqual(value['inventory']['warp']['eligible_files'], 0)

    def test_namespace_budget_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            item = {'id': 'goose-001', 'agent': 'goose', 'bytes': 1,
                    'size_stratum': 'under-16-KiB', 'path': str(out/'source.db')}
            destination = out/item['id']
            destination.mkdir()
            (destination/'incomplete.jsonl').touch()
            conversion = json.dumps({'files': 1, 'sessions': 1, 'records': 2,
                                     'source_bytes': 1, 'diagnostics': {}}).encode()
            with patch('database_corpus.run_command', side_effect=[(0, conversion, .01),
                                                                  (None, b'', .01)]) as run:
                result = check_file(item, Path('/example/asr'), Path('/example/validator'),
                                    out, 10, {'goose': 'example-profile'})
            self.assertEqual(result['status'], 'validation_timeout')
            self.assertFalse(destination.exists())
            self.assertEqual(run.call_args_list[0].args[0][-2:], ['--namespace', 'example-profile'])
            self.assertLessEqual(run.call_args_list[1].args[1], 10)

    def test_summary_separates_agent_diagnostic_codes(self):
        manifest = catalog([], 100)
        results = {'one': {'agent': 'goose', 'status': 'passed',
                           'conversion': {'sessions': 1, 'records': 3,
                                          'diagnostics': {'secret_redacted': 2}},
                           'validation': {'counts': {'warning:unknown-type': 1}}}}
        value = summarize(manifest, results)['by_agent']
        self.assertEqual(value['goose']['conversion_codes'], {'secret_redacted': 2})
        self.assertEqual(value['goose']['validation_codes'], {'warning:unknown-type': 1})
        self.assertEqual(value['warp']['conversion_codes'], {})


if __name__ == '__main__':
    unittest.main()
