from contextlib import closing
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixlab.dashboard import generate, load_task
from fixlab.cli import main


class DashboardTests(unittest.TestCase):
    def fixture(self, root, name='addition', report=True):
        state = root / name / 'state.sqlite'
        state.parent.mkdir(parents=True)
        with closing(sqlite3.connect(state)) as db, db:
            db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, kind TEXT, payload TEXT)')
            db.execute('INSERT INTO events(kind,payload) VALUES (?,?)',
                       ('task', json.dumps({'task': '<script>alert(1)</script>', 'root': 'fixture'})))
            db.execute('INSERT INTO events(kind,payload) VALUES (?,?)',
                       ('message', json.dumps({'role': 'assistant', 'content': '</script><img src=x onerror=alert(1)>'})))
        artifacts = state.parent / 'state-artifacts'
        artifacts.mkdir()
        if report:
            (artifacts / 'report.json').write_text(json.dumps({'repair_success': True, 'tokens': {'total_tokens': 10},
                'model': 'fixture', 'execution_seconds': 2.5, 'acceptance': {'passed': True}}), encoding='utf-8')
        (artifacts / 'changes.diff').write_text('--- a/file.py\n+++ b/file.py\n-<script>bad()</script>\n+fixed\n', encoding='utf-8')
        return state

    def test_readonly_generation_escapes_all_untrusted_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = self.fixture(root)
            original = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            out = root / 'report.html'
            result = generate(root, out)
            self.assertEqual(result['success'], 1)
            text = out.read_text(encoding='utf-8')
            self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', text)
            self.assertNotIn('<img src=x', text)
            self.assertNotIn('<script>bad()', text)
            self.assertIn('class="added"', text)
            for p, digest in original.items():
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), digest)
            self.assertEqual(generate(state, out)['tasks'], 1)

    def test_missing_report_and_corrupt_database_do_not_hide_other_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root, 'good')
            self.fixture(root, 'pending', report=False)
            (root / 'broken.sqlite').write_bytes(b'not sqlite')
            result = generate(root, root / 'report.html')
            self.assertEqual(result['tasks'], 3)
            self.assertEqual(result['unknown'], 2)
            self.assertIn('轨迹数据库不可读', (root/'report.html').read_text(encoding='utf-8'))

    def test_bad_report_and_bad_payload_are_tolerated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = self.fixture(root)
            (state.parent/'state-artifacts/report.json').write_text('[]')
            with closing(sqlite3.connect(state)) as db, db:
                db.execute("INSERT INTO events(kind,payload) VALUES ('message','broken')")
            result = generate(state, root/'report.html')
            self.assertEqual(result['unknown'], 1)
            self.assertIn('事件内容无法解析', (root/'report.html').read_text(encoding='utf-8'))

    def test_output_protection_and_missing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out = root/'user.html'
            out.write_text('user content')
            with self.assertRaisesRegex(ValueError, 'overwrite'): generate(root, out)
            self.assertEqual(out.read_text(), 'user content')
            with self.assertRaisesRegex(ValueError, 'does not exist'): generate(root/'missing', root/'report.html')
            with self.assertRaisesRegex(ValueError, '.html'): generate(root, root/'state.sqlite')

    def test_event_limit_is_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            state = self.fixture(Path(folder))
            with patch('fixlab.dashboard.MAX_EVENTS', 1):
                row = load_task(state)
            self.assertEqual(len(row['events']), 1)
            self.assertTrue(row['warnings'])

    def test_cli_never_loads_model_config(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'report.html'
            with patch('sys.argv', ['fixlab', 'dashboard', folder, '--output', str(out)]), \
                 patch('fixlab.cli.load_config', side_effect=AssertionError('No API access')), patch('builtins.print'):
                main()
            self.assertTrue(out.is_file())
