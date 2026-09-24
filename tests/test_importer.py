import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from fixlab.importer import import_task
from fixlab.benchmark import evaluate
from fixlab.core import DemoModel

class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=self.root/'source';self.repo.mkdir()
        self.git('init');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        (self.repo/'calculator.py').write_text('def add(a,b): return a-b\n')
        (self.repo/'.env').write_text('PRIVATE=fixture-only\n')
        self.git('add','.');self.git('commit','-m','Bug fixture')
        self.commit=self.git('rev-parse','HEAD').strip()
        (self.repo/'calculator.py').write_text('def add(a,b): return 999\n')
        self.description=self.root/'issue.txt';self.description.write_text('Fix addition')
        self.public=self.root/'public';self.public.mkdir()
        self.hidden=self.root/'hidden';self.hidden.mkdir()
        code='import unittest\nfrom calculator import add\nclass Tests(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n'
        (self.public/'test_public_add.py').write_text(code)
        (self.hidden/'test_hidden_add.py').write_text(code.replace('add(2,3),5','add(-2,2),0'))
    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],stderr=subprocess.DEVNULL,text=True)
    def import_one(self,output=None,commit=None):
        return import_task(self.repo,commit or self.commit,output or self.root/'suite/addition',self.description,self.public,self.hidden)
    def test_snapshot_ignores_dirty_tree_and_runs_in_benchmark(self):
        result=self.import_one();target=Path(result['output'])
        self.assertIn('a-b',(target/'repo/calculator.py').read_text())
        self.assertIn('999',(self.repo/'calculator.py').read_text())
        self.assertFalse((target/'repo/.env').exists())
        self.assertFalse((target/'repo/test_hidden_add.py').exists())
        self.assertTrue((target/'hidden/test_hidden_add.py').exists())
        metadata=json.loads((target/'task.json').read_text())
        self.assertEqual(metadata['source']['commit'],self.commit)
        result=evaluate(self.root/'suite',self.root/'eval',DemoModel)
        self.assertEqual(result['successes'],1)
    def test_refusal_does_not_overwrite_or_modify_source(self):
        self.import_one()
        with self.assertRaisesRegex(ValueError,'already exists'): self.import_one()
        with self.assertRaisesRegex(ValueError,'outside'): self.import_one(self.repo/'task')
        with self.assertRaises(ValueError): self.import_one(self.root/'other','missing-commit')
        self.assertFalse((self.root/'other').exists())
    def test_invalid_hidden_file_and_collision_rejected(self):
        (self.hidden/'answer.txt').write_text('unexpected')
        with self.assertRaisesRegex(ValueError,'flat'):self.import_one()
        (self.hidden/'answer.txt').unlink()
        (self.repo/'test_public_add.py').write_text('# collision')
        self.git('add','test_public_add.py');self.git('commit','-m','Collision fixture')
        with self.assertRaisesRegex(ValueError,'conflicts'):self.import_one(commit='HEAD')
        self.assertFalse((self.root/'suite').exists())
