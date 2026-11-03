"""Document sampler includes its native formats without aliases or display copies."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('document_sampler', Path(__file__).with_name('check-documents.py'))
sampler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sampler)


class Documents(unittest.TestCase):
    def test_native_formats_and_alias_exclusion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'state.db').write_bytes(b'fixture')
            (root/'config.json').write_text('{}')
            (root/'alias').symlink_to(root/'state.db')
            value = sampler.catalog({'hermes': [root, root]}, 100)
            self.assertEqual(value['inventory']['hermes']['eligible_files'], 1)
            self.assertEqual(len(value['files']), 1)
            self.assertEqual(value['inventory']['cline']['eligible_files'], 0)

    def test_largest_files_and_file_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(105):
                (root/f'{index}.json').write_bytes(b'x' * (index + 1))
            value = sampler.catalog({'auggie': [root]}, 100)
            self.assertEqual(value['inventory']['auggie']['eligible_files'], 105)
            self.assertEqual(len(value['files']), 100)
            self.assertEqual(value['files'][0]['bytes'], 105)

    def test_event_paths_are_selected_but_sidecars_are_not(self):
        self.assertTrue(sampler.selected('openhands', Path('conversations/session/events/1.json')))
        self.assertFalse(sampler.selected('openhands', Path('conversations/session/state.json')))
        self.assertFalse(sampler.selected('nanoclaw', Path('data/v2.db-wal')))
