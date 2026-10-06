import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixlab.core import APIModel, DemoModel, Workspace
from fixlab.evaluation import run_evaluated
from fixlab.comparison import compare, aggregate


class ComparisonTests(unittest.TestCase):
    def test_off_removes_self_check_from_api_request(self):
        response = {'choices':[{'message':{'role':'assistant','content':'done'}}]}
        for enabled in (False, True):
            with patch('fixlab.core.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as call:
                APIModel('test', 'unused', 'https://example.invalid', self_check=enabled).reply([])
                request = json.loads(call.call_args.args[0].data)
                names = [t['function']['name'] for t in request['tools']]
                self.assertEqual('self_check' in names, enabled)

    def test_off_finishes_without_self_check_and_cannot_switch_on_resume(self):
        class Model(APIModel):
            def reply(self, messages):
                self_messages = [m for m in messages if m['role']=='user' and 'derive a checklist' in m['content']]
                assert not self_messages
                return DemoModel().reply(messages)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); repo=root/'repo'; repo.mkdir()
            (repo/'calculator.py').write_text('def add(a,b): return a-b\n')
            (repo/'test_public.py').write_text('import unittest\nfrom calculator import add\nclass Tests(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n')
            state=root/'state.sqlite'
            report=run_evaluated(Workspace(repo),Model('test','unused','https://example.invalid',self_check=False),'fix',state)
            self.assertTrue(report['repair_success'])
            self.assertFalse(report['self_check_enabled'])
            self.assertEqual(report['self_check_calls'],0)
            with self.assertRaisesRegex(ValueError,'original self-check mode'):
                run_evaluated(Workspace(repo),Model('test','unused','https://example.invalid',self_check=True),'fix',state)

    def test_repeated_pairs_use_same_sources_and_alternate_order(self):
        calls=[]
        def fake_evaluate(suite, output, factory, max_steps, executor=None, budget_options=None):
            calls.append((str(suite),str(output),factory().self_check_enabled,max_steps))
            return {'token_usage_complete':True,'results':[{'task_id':'addition','source_sha256':'same',
                    'repair_success':True,'tokens':{'total_tokens':10},'execution_seconds':2}]}
        def factory(enabled):
            return APIModel('test','unused','https://example.invalid',self_check=enabled)
        with tempfile.TemporaryDirectory() as folder, patch('fixlab.comparison.evaluate',side_effect=fake_evaluate):
            output=Path(folder)/'comparison'
            result=compare('benchmarks',output,factory,repeats=2,task_id='addition')
            self.assertEqual([c[2] for c in calls],[False,True,True,False])
            self.assertEqual(len({c[0] for c in calls}),1)
            self.assertEqual(len({c[1] for c in calls}),4)
            self.assertEqual(result['groups']['on']['success_rate'],1)
            self.assertEqual(result['groups']['off']['tokens_per_success'],10)
            self.assertEqual(len(result['pairs']),2)
            self.assertEqual(result['status'],'completed')
            self.assertTrue((output/'comparison.md').exists())
            self.assertTrue((output/'suite/addition/repo/calculator.py').exists())
            with self.assertRaises(FileExistsError):
                compare('benchmarks',output,factory,repeats=2,task_id='addition')

    def test_unknown_usage_not_zero_and_task_mismatch_rejected(self):
        def batch(mode, digest='same'):
            return {'mode':mode,'repeat':1,'summary':{'token_usage_complete':False,'results':[
                {'task_id':'task','source_sha256':digest,'repair_success':False,
                 'tokens':{'total_tokens':None},'error_type':'TimeoutError'}]}}
        groups,pairs=aggregate([batch('off'),batch('on')],1)
        self.assertIsNone(groups['on']['mean_tokens'])
        self.assertIsNone(groups['on']['tokens_per_success'])
        self.assertIsNone(groups['on']['mean_execution_seconds'])
        self.assertEqual(groups['on']['execution_errors'],1)
        with self.assertRaisesRegex(ValueError,'fingerprints'):
            aggregate([batch('off'),batch('on','changed')],1)

    def test_interruption_preserves_completed_batches(self):
        factory=lambda enabled: APIModel('test','unused','https://example.invalid',self_check=enabled)
        summary={'results':[],'token_usage_complete':False}
        with tempfile.TemporaryDirectory() as folder, patch('fixlab.comparison.evaluate',side_effect=[summary,KeyboardInterrupt]):
            output=Path(folder)/'comparison'
            with self.assertRaises(KeyboardInterrupt):
                compare('benchmarks',output,factory,repeats=1,task_id='addition')
            saved=json.loads((output/'comparison.json').read_text())
            self.assertEqual(saved['status'],'interrupted')
            self.assertEqual(len(saved['runs']),1)
