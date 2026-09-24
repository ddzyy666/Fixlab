import json
import tempfile
import unittest
from pathlib import Path
from fixlab.core import APIModel, Store
from fixlab.benchmark import evaluate
from fixlab.resume import inspect_resume,resume_task

class Interrupted(APIModel):
    def __init__(self):
        super().__init__('fixture-model','unused','https://example.invalid',self_check=False)
    def reply(self,messages):
        if any(m['role']=='tool' for m in messages): raise ConnectionError('offline')
        return {'role':'assistant','content':None,'tool_calls':[{'id':'write','type':'function','function':{'name':'write_file','arguments':json.dumps({'path':'calculator.py','content':'def add(a,b): return a+b\n'})}}]}, {'total_tokens':10}

class Finish(Interrupted):
    def reply(self,messages):
        return {'role':'assistant','content':'done'}, {'total_tokens':5}

class ResumeTests(unittest.TestCase):
    def test_interrupted_passing_patch_recovers_and_updates_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'eval'
            first=evaluate('benchmarks',out,Interrupted,task_id='addition')
            row=first['results'][0];state=Path(row['state'])
            self.assertEqual(row['patch_status'],'passed')
            self.assertEqual(row['execution_status'],'interrupted')
            self.assertEqual(row['self_check_status'],'disabled')
            self.assertFalse(row['repair_success'])
            plan=inspect_resume(state)
            self.assertEqual(plan['model'],'fixture-model')
            self.assertEqual(plan['used_steps'],1)
            self.assertEqual(plan['max_steps'],12)
            result=resume_task(state,model_factory=lambda p:Finish())
            self.assertTrue(result['repair_success'])
            self.assertIsNone(result['error_type'])
            batch=json.loads((out/'summary.json').read_text())
            self.assertEqual(batch['successes'],1)
            self.assertTrue(batch['contains_resumed_trials'])
            self.assertTrue(list((out/'resume-history').glob('*.json')))
            before=state.read_bytes()
            resume_task(state,model_factory=lambda p:self.fail('Completed task called model'))
            self.assertEqual(before,state.read_bytes())

    def test_missing_and_uncertain_states_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'absent.sqlite'
            with self.assertRaises(ValueError):inspect_resume(path)
            self.assertFalse(path.exists())
            out=Path(temp)/'eval';row=evaluate('benchmarks',out,Interrupted,task_id='addition')['results'][0]
            state=Path(row['state'])
            with self.assertRaisesRegex(ValueError,'No model steps'):
                resume_task(state,max_steps=1,model_factory=lambda p:self.fail())
            store=Store(state);store.add('tool_started',{'id':'uncertain','function':{'name':'write_file'}});store.db.close()
            with self.assertRaisesRegex(ValueError,'Uncertain'):inspect_resume(state)
