import json
from pathlib import Path
import sys
import tempfile
import unittest
from sample_corpus import catalog, percentiles, run_command, select, stratum, summarize


class SampleTests(unittest.TestCase):
    def test_selection_includes_largest_and_balances_nonempty_size_strata(self):
        values = [{'path': f'file-{index}', 'bytes': size + index}
                  for size in (100, 20_000, 200_000, 2_000_000, 20_000_000, 200_000_000)
                  for index in range(100)]
        # Paths in the fixture must be unique across strata.
        for index, value in enumerate(values):
            value['path'] += f'-{index}'
        chosen = select(values)
        self.assertEqual(len(chosen), 300)
        self.assertEqual(len({item['path'] for item in chosen}), 300)
        self.assertEqual(chosen[:10], sorted(values, key=lambda item: (-item['bytes'], item['path']))[:10])
        self.assertEqual({stratum(item['bytes']) for item in chosen}, set(range(6)))
        self.assertEqual(chosen, select(list(reversed(values))))

    def test_catalog_excludes_aliases_and_unreadable_or_redundant_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'native.jsonl').write_text(json.dumps({'type': 'unknown'}) + '\n')
            (root/'native.jsonl.zst').write_bytes(b'companion')
            (root/'alias.jsonl').symlink_to(root/'native.jsonl')
            (root/'missing.jsonl').symlink_to(root/'absent')
            result = catalog([f'codex={root}'], 300)
            self.assertEqual(len(result['files']), 1)
            counts = result['inventory']['codex']
            self.assertEqual(counts['file_aliases'], 1)
            self.assertEqual(counts['unavailable_entries'], 1)
            self.assertEqual(counts['compressed_companions'], 1)

    def test_deadline_kills_only_owned_process_and_percentiles_use_completed_values(self):
        code, output, elapsed = run_command([sys.executable, '-c', 'import time; time.sleep(10)'], .05)
        self.assertIsNone(code)
        self.assertEqual(output, b'')
        self.assertLess(elapsed, 2)
        self.assertEqual(percentiles([4, 1, 3, 2]),
                         {'p50': 2, 'p90': 4, 'p95': 4, 'p99': 4, 'max': 4})
        self.assertEqual(percentiles([]), {})

    def test_summary_separates_censored_timeouts_from_completed_conversions(self):
        manifest = {'size_basis': 'stored file bytes', 'files': [{'agent': 'codex'}]}
        results = {'one': {'agent': 'codex', 'status': 'passed', 'conversion_exit': 0,
                           'conversion_seconds': 2, 'validation': {'counts': {'warning:unknown-type': 1}}},
                   'two': {'agent': 'codex', 'status': 'conversion_timeout',
                           'conversion_exit': None, 'conversion_seconds': 300}}
        result = summarize(manifest, results, 300)
        group = result['by_agent']['codex']
        self.assertEqual(group['observed_conversion_seconds']['p99'], 300)
        self.assertEqual(group['completed_conversion_seconds']['p99'], 2)
        self.assertEqual(group['conversion_timeouts'], 1)
        self.assertEqual(result['validation_codes'], {'warning:unknown-type': 1})


if __name__ == '__main__':
    unittest.main()
