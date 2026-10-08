import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fixlab.core import APIModel, Workspace


class ReplaceTextTests(unittest.TestCase):
    def test_registered_in_actual_model_request(self):
        response = {'choices': [{'message': {'role': 'assistant', 'content': 'done'}}]}
        with patch('fixlab.core.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as call:
            APIModel('fixture', 'unused', 'https://example.invalid').reply([])
        tools = {t['function']['name']: t['function'] for t in json.loads(call.call_args.args[0].data)['tools']}
        self.assertIn('read_file', tools)
        self.assertIn('read_file_lines', tools)
        self.assertEqual(set(tools['replace_text']['parameters']['required']), {'path', 'old_text', 'new_text'})

    def test_local_edit_preserves_other_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'sample.py'
            original = b'\xef\xbb\xbf# header\r\ndef add(a,b):\r\n    return a-b\r\n# footer\r\n'
            path.write_bytes(original)
            Workspace(folder).execute('replace_text', {'path': 'sample.py', 'old_text': 'return a-b', 'new_text': 'return a+b'})
            self.assertEqual(path.read_bytes(), original.replace(b'return a-b', b'return a+b'))

    def test_invalid_or_ambiguous_edits_leave_file_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'sample.py'
            path.write_bytes(b'aaaa\r\n')
            workspace = Workspace(folder)
            for old, new in [('', 'x'), ('missing', 'x'), ('aa', 'x'), ('aaa', 'x'), ('aaaa', 'aaaa'), (1, 'x'), ('aaaa\n', 'x')]:
                with self.subTest(old=old), self.assertRaises(ValueError):
                    workspace.execute('replace_text', {'path': 'sample.py', 'old_text': old, 'new_text': new})
                self.assertEqual(path.read_bytes(), b'aaaa\r\n')
            for target in ('../outside.py', '.git/config', 'fixlab.local.toml'):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    workspace.execute('replace_text', {'path': target, 'old_text': 'a', 'new_text': 'b'})
