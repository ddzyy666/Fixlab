import base64
import json
import unittest
from pathlib import Path
from fixlab.evaluation import acceptance, snapshot


class ChallengeSuiteTests(unittest.TestCase):
    def test_reference_and_incomplete_repairs(self):
        refs=json.loads(Path('tests/fixtures/challenge_references.json').read_text(encoding='utf-8'))
        for name, variants in refs.items():
            with self.subTest(task=name):
                root=Path('benchmarks_challenge')/name
                before=snapshot(root/'repo'); hidden=snapshot(root/'hidden')
                baseline=acceptance(before,before)
                self.assertFalse(baseline['passed'])
                self.assertEqual(baseline['errors'],0)
                for kind in ('partial','fixes'):
                    candidate={**before,**{k:base64.b64encode(v.encode()).decode() for k,v in variants[kind].items()}}
                    public=acceptance(before,candidate)
                    combined=acceptance(before,candidate,hidden=hidden)
                    self.assertTrue(public['passed'],public['output'])
                    self.assertEqual(combined['passed'],kind=='fixes',combined['output'])
                    self.assertGreater(combined['tests_run'],public['tests_run'])
                self.assertEqual(before,snapshot(root/'repo'))
