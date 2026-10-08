import copy
import unittest
from fixlab.context import build_context, estimate
from fixlab.budget import BudgetExceeded


def history():
    result=[{'role':'system','content':'rules'}, {'role':'user','content':'original requirements'}]
    for i in range(12):
        result += [{'role':'assistant','content':None,'tool_calls':[{'id':str(i),'type':'function',
                    'function':{'name':'read_file','arguments':'{"path":"code.py"}'}}]},
                   {'role':'tool','tool_call_id':str(i),'content':'x'*3000}]
    return result


class ContextTests(unittest.TestCase):
    def test_short_context_unchanged_and_inputs_not_mutated(self):
        messages=history()[:4];before=copy.deepcopy(messages)
        built=build_context(messages,[],16000)
        self.assertEqual(built.messages,before)
        self.assertFalse(built.audit['compressed'])
        self.assertEqual(messages,before)

    def test_compaction_preserves_requirements_and_tool_pairs(self):
        messages=history();before=copy.deepcopy(messages)
        built=build_context(messages,[],5000)
        self.assertTrue(built.audit['compressed'])
        self.assertEqual(built.messages[:2],messages[:2])
        self.assertEqual(built.messages[-2:],messages[-2:])
        self.assertLessEqual(estimate(built.messages,[])+2048,5000)
        self.assertEqual(messages,before)
        for i,m in enumerate(built.messages):
            if m['role']=='tool':
                self.assertEqual(built.messages[i-1]['tool_calls'][0]['id'],m['tool_call_id'])
        self.assertEqual(build_context(messages,[],5000).messages,built.messages)

    def test_oversized_required_content_stops(self):
        with self.assertRaisesRegex(BudgetExceeded,'context_limit'):
            build_context([{'role':'user','content':'requirements'*5000}],[],5000)

    def test_pending_and_orphan_tools_rejected(self):
        for messages in (history()[:-1],[{'role':'tool','tool_call_id':'x','content':'x'}]):
            with self.assertRaises(ValueError):build_context(messages,[],5000)

    def test_test_evidence_requires_matching_fingerprint(self):
        messages=history()
        messages[2]['tool_calls'][0]['function']={'name':'run_tests','arguments':'{}'}
        messages[3]['content']='{"exit_code":0}'
        observation=[('tool_observation',{'tool_call_id':'0','stable':True,'hash':'current'})]
        for events,current,expected in [(observation,'current',True),(observation,'changed',False),([], 'current',False)]:
            built=build_context(messages,[],5000,events,current)
            import json
            summary=next(m['content'] for m in built.messages if m['role']=='user' and m['content'].startswith('Harness history'))
            record=json.loads(summary.split('\n',1)[1])
            self.assertEqual(record['latest_checks']['run_tests']['valid_for_current_files'],expected)

    def test_multiple_calls_are_kept_together(self):
        messages=history()
        messages[-2]['tool_calls'].append({'id':'extra','type':'function','function':{'name':'list_files','arguments':'{}'}})
        messages.append({'role':'tool','tool_call_id':'extra','content':'files'})
        built=build_context(messages,[],6000)
        self.assertEqual(built.messages[-3:],messages[-3:])

    def test_run_stops_before_api_when_required_context_is_too_large(self):
        import tempfile
        from unittest.mock import patch
        from fixlab.core import APIModel, Workspace
        from fixlab.evaluation import run_evaluated
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repo=root/'repo';repo.mkdir()
            (repo/'test_public.py').write_text('import unittest\nclass Tests(unittest.TestCase):\n def test_bad(self): self.fail("bug")\n')
            model=APIModel('fixture','unused','https://example.invalid',self_check=False)
            with patch.object(model,'reply',side_effect=AssertionError('API must not run')):
                report=run_evaluated(Workspace(repo),model,'requirement '*3000,root/'state.sqlite',
                                     budget_options={'context_max_tokens':3000})
            self.assertEqual(report['budget_stop_reason'],'context_limit')
            self.assertIsNone(report['error_type'])
