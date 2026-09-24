import json
import tempfile
import unittest
from pathlib import Path
from fixlab.core import APIModel, Workspace
from fixlab.evaluation import run_evaluated, snapshot
from fixlab.selfcheck import check

CODE = 'import unittest\nfrom calculator import add\nclass Tests(unittest.TestCase):\n def test_negative(self): self.assertEqual(add(-2,2),0)\n'

class SelfCheckTests(unittest.TestCase):
    def test_diagnostics_are_temporary_and_zero_tests_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'calculator.py').write_text('def add(a,b): return a-b\n')
            before=snapshot(root)
            self.assertFalse(check(Workspace(root),CODE)['passed'])
            self.assertFalse(check(Workspace(root),'# no tests')['passed'])
            self.assertEqual(before,snapshot(root))

    def test_finish_requires_self_check_and_rechecks_latest_code(self):
        class Model(APIModel):
            def __init__(self):
                super().__init__('scripted-test','unused','https://example.invalid')
                self.turn=0
            def reply(self,messages):
                self.turn+=1
                if self.turn==1:
                    name,args='write_file',{'path':'calculator.py','content':'def add(a,b): return a+b\n'}
                elif self.turn==2 or self.turn>=5:
                    return {'role':'assistant','content':'done'},{}
                elif self.turn==3:
                    name,args='self_check',{'requirements':'Addition supports negative integers','test_code':CODE}
                else:
                    name,args='write_file',{'path':'calculator.py','content':'def add(a,b): return 5\n'}
                return {'role':'assistant','content':None,'tool_calls':[{'id':str(self.turn),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]},{}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); repo=root/'repo'; repo.mkdir()
            (repo/'calculator.py').write_text('def add(a,b): return a-b\n')
            (repo/'test_public.py').write_text('import unittest\nfrom calculator import add\nclass Tests(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n')
            report=run_evaluated(Workspace(repo),Model(),'Fix addition',root/'state.sqlite',5)
            self.assertEqual(report['agent_status'],'budget_exhausted')
            self.assertEqual(report['self_check_calls'],1)
            self.assertFalse(report['self_check_final']['passed'])
            self.assertEqual(report['completion_rejections'],2)
            self.assertTrue(report['public_acceptance']['passed'])
            self.assertFalse((repo/'test_fixlab_self_check.py').exists())
