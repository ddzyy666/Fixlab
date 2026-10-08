import json
import tempfile
import unittest
from pathlib import Path
from fixlab.core import TOOLS, Workspace


class SearchTests(unittest.TestCase):
    def test_long_file_literal_match_and_read_followup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'large.py'
            path.write_text('# padding\n' * 2000 + 'def split_after(iterable):\n    pass\n', encoding='utf-8')
            workspace = Workspace(folder)
            result = json.loads(workspace.execute('search_text', {'path': '.', 'query': 'def split_after(', 'max_results': 10}))
            self.assertEqual(result['matches'][0]['line'], 2001)
            self.assertEqual(result['matches'][0]['path'], 'large.py')
            self.assertFalse(result['truncated'])
            self.assertIn('def split_after(', workspace.execute('read_file_lines', {'path': 'large.py', 'start_line': 2001, 'end_line': 2002}))
            self.assertIn('search_text', [t['function']['name'] for t in TOOLS])

    def test_exclusions_limits_and_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('.env', '.env.local', 'fixlab.local.toml', 'private.key'):
                (root/name).write_text('needle')
            (root/'a.py').write_text('needle\nneedle\n')
            (root/'binary').write_bytes(b'needle\0')
            w = Workspace(root)
            result = json.loads(w.execute('search_text', {'path': '.', 'query': 'needle', 'max_results': 1}))
            self.assertTrue(result['truncated'])
            self.assertEqual(result['matches'][0]['path'], 'a.py')
            for path in ('../outside', '.env.local', 'private.key'):
                with self.assertRaises(ValueError):w.execute('search_text', {'path': path, 'query': 'needle', 'max_results': 10})
            for query, limit in (('', 10), ('x\ny', 10), ('x', True), ('x', 101)):
                with self.assertRaises(ValueError):w.execute('search_text', {'path': '.', 'query': query, 'max_results': limit})
            result = json.loads(w.execute('search_text', {'path': 'a.py', 'query': 'NEEDLE', 'max_results': 10}))
            self.assertEqual(result['matches'], [])

    def test_search_does_not_change_files_and_reports_binary_skips(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'text.py').write_bytes(b'needle\r\n')
            (root/'binary').write_bytes(b'\xff')
            original = (root/'text.py').read_bytes()
            result = json.loads(Workspace(root).execute('search_text', {'path': '.', 'query': 'needle', 'max_results': 10}))
            self.assertEqual(result['files_skipped'], 1)
            self.assertEqual((root/'text.py').read_bytes(), original)
