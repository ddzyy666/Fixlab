import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fixlab.core import DemoModel,Workspace
from fixlab.evaluation import run_evaluated
from fixlab.delivery import deliver
from fixlab.cli import main

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=self.root/'source';self.repo.mkdir()
        self.git('init');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid');self.git('config','core.autocrlf','false')
        self.original='def add(a,b): return a-b\n'
        (self.repo/'calculator.py').write_text(self.original)
        (self.repo/'test_public.py').write_text('import unittest\nfrom calculator import add\nclass Tests(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n')
        self.git('add','.');self.git('commit','-m','Bug')
        self.commit=self.git('rev-parse','HEAD').strip()
        self.work=self.root/'agent';self.work.mkdir()
        for p in self.repo.glob('*.py'): (self.work/p.name).write_bytes(p.read_bytes())
        self.state=self.root/'run/state.sqlite'
        run_evaluated(Workspace(self.work),DemoModel(),'fix',self.state)
    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],stderr=subprocess.DEVNULL,text=True)
    def test_preview_then_worktree_preserves_source(self):
        plan=deliver(self.state,self.repo,self.commit)
        self.assertFalse(plan['applied']);self.assertEqual(plan['changed_files'],['calculator.py'])
        branch=self.git('branch','--show-current')
        target=self.root/'review'
        result=deliver(self.state,self.repo,self.commit,'fixlab/test',target,True)
        self.assertEqual(result['status'],'ready_for_review')
        self.assertEqual((self.repo/'calculator.py').read_text(),self.original)
        self.assertEqual(self.git('branch','--show-current'),branch)
        self.assertFalse(self.git('status','--porcelain').strip())
        self.assertIn('return a + b',(target/'calculator.py').read_text())
        self.assertTrue(result['acceptance']['passed'])
    def test_dirty_source_and_wrong_commit_rejected(self):
        (self.repo/'calculator.py').write_text('dirty')
        with self.assertRaisesRegex(ValueError,'clean'):deliver(self.state,self.repo,self.commit)
        (self.repo/'calculator.py').write_text(self.original)
        self.git('commit','--allow-empty','-m','New head')
        with self.assertRaisesRegex(ValueError,'HEAD differs'):deliver(self.state,self.repo,self.commit)
    def test_changed_test_rejected(self):
        (self.work/'test_public.py').write_text('# altered')
        with self.assertRaisesRegex(ValueError,'tests or protected'):deliver(self.state,self.repo,self.commit)
    def test_stale_passing_report_revalidated(self):
        (self.work/'calculator.py').write_text('def add(a,b): return 999\n')
        with self.assertRaisesRegex(ValueError,'fresh acceptance'):
            deliver(self.state,self.repo,self.commit,'fixlab/stale',self.root/'review',True)
        self.assertFalse((self.root/'review').exists())
        self.assertFalse(self.git('branch','--list','fixlab/stale').strip())
    def test_friendly_keyboard_interrupt(self):
        with patch('fixlab.cli._main',side_effect=KeyboardInterrupt),patch('sys.stderr'):
            with self.assertRaises(SystemExit) as result:main()
            self.assertEqual(result.exception.code,130)
