import tempfile
import unittest
from pathlib import Path
from fixlab.benchmark import evaluate
from fixlab.core import DemoModel
from fixlab.evaluation import acceptance, snapshot



class BenchmarkTests(unittest.TestCase):
    def test_all_fixtures_fail_initial_acceptance(self):
        for repo in Path('benchmarks').glob('*/repo'):
            with self.subTest(repo=repo):
                files = snapshot(repo.resolve())
                result = acceptance(files, files)
                self.assertGreater(result['tests_run'], 0)
                self.assertFalse(result['passed'])
                self.assertEqual(result['errors'], 0)

    def test_success_and_source_unchanged(self):
        before = snapshot(Path('benchmarks/addition/repo').resolve())
        with tempfile.TemporaryDirectory() as temp:
            result = evaluate('benchmarks', Path(temp)/'out', DemoModel, task_id='addition')
            self.assertEqual(result['successes'], 1)
            self.assertFalse(result['token_usage_complete'])
            self.assertEqual(result['results'][0]['outcome'], 'repaired')
            with self.assertRaises(FileExistsError):
                evaluate('benchmarks', Path(temp)/'out', DemoModel, task_id='addition')
        self.assertEqual(before, snapshot(Path('benchmarks/addition/repo').resolve()))

    def test_provider_failures_do_not_stop_batch(self):
        class Broken:
            def reply(self, messages):
                raise RuntimeError('secret-provider-error')
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'out'
            result = evaluate('benchmarks', out, Broken)
            self.assertEqual(result['tasks_finished'], 5)
            self.assertEqual(result['successes'], 0)
            self.assertTrue(all(r['outcome']=='execution_error' for r in result['results']))
            self.assertNotIn('secret-provider-error', (out/'summary.json').read_text())
