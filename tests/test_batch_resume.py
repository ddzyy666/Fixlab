import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixlab.batch_resume import resume_batch
from fixlab.benchmark import evaluate
from fixlab.core import APIModel, DemoModel, Store, Workspace
from fixlab.evaluation import run_evaluated
from fixlab.locking import BusyError, exclusive
from fixlab.resume import resume_task


class Repair(APIModel):
    def __init__(self):
        super().__init__('fixture-model', 'unused', 'https://example.invalid', self_check=False)

    def reply(self, messages):
        message, _ = DemoModel().reply(messages)
        return message, {'total_tokens': 10}


class Crash(Repair):
    def reply(self, messages):
        if any(m['role'] == 'tool' for m in messages):
            raise KeyboardInterrupt
        return super().reply(messages)


class BatchResumeTests(unittest.TestCase):
    def suite(self, root):
        suite = root/'suite'
        for name in ('a', 'b', 'c'):
            shutil.copytree('benchmarks/addition', suite/name)
        return suite

    def test_resume_current_unstarted_and_skip_completed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); suite = self.suite(root); out = root/'batch'
            models = iter([Repair(), Crash(), Repair()])
            with self.assertRaises(KeyboardInterrupt):
                evaluate(suite, out, lambda: next(models))
            original_state = (out/'a/state.sqlite').read_bytes()
            inventory = resume_batch(out, inspect=True)
            self.assertEqual([x['action'] for x in inventory['tasks']], ['skip_completed', 'resume', 'start'])
            # No dependency on source fixtures after freezing.
            (suite/'c/repo/calculator.py').write_text('invalid source')
            calls = []
            def factory(plan):
                calls.append(plan['model'])
                return Repair()
            result = resume_batch(out, model_factory=factory)
            self.assertEqual(result['status'], 'finished')
            self.assertEqual(len(calls), 2)
            self.assertEqual((out/'a/state.sqlite').read_bytes(), original_state)
            summary = json.loads((out/'summary.json').read_text())
            self.assertEqual(summary['tasks_finished'], 3)
            self.assertEqual(summary['successes'], 3)
            resume_batch(out, model_factory=lambda p: self.fail('Completed task called model'))
            self.assertEqual(json.loads((out/'summary.json').read_text())['tasks_finished'], 3)

    def test_block_uncertain_task_but_continue_other_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); out = root/'batch'
            models = iter([Crash(), Repair(), Repair()])
            with self.assertRaises(KeyboardInterrupt): evaluate(self.suite(root), out, lambda: next(models))
            state = out/'a/state.sqlite'
            store = Store(state)
            store.add('tool_started', {'id': 'unknown', 'function': {'name': 'write_file'}})
            store.db.close()
            result = resume_batch(out, model_factory=lambda p: Repair())
            self.assertEqual(result['status'], 'finished_with_pending')
            self.assertEqual(result['tasks'][0]['status'], 'blocked')
            self.assertEqual(json.loads((out/'summary.json').read_text())['successes'], 2)

    def test_legacy_missing_row_is_repaired_and_unknown_tasks_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'batch'
            models=iter([Crash(),Repair(),Repair()])
            with self.assertRaises(KeyboardInterrupt):evaluate(self.suite(root),out,lambda:next(models))
            (out/'batch-plan.json').unlink()
            result=resume_batch(out,model_factory=lambda p:Repair())
            self.assertEqual(result['unrecoverable_unstarted'],2)
            self.assertEqual(json.loads((out/'summary.json').read_text())['successes'],1)

    def test_second_interrupt_keeps_log_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'batch'
            with self.assertRaises(KeyboardInterrupt):evaluate('benchmarks',out,Crash,task_id='addition')
            with self.assertRaises(KeyboardInterrupt):resume_batch(out,model_factory=lambda p:Crash())
            log=next((out/'resume-history').glob('batch-*.json'))
            self.assertEqual(json.loads(log.read_text())['status'],'interrupted')
            self.assertEqual(resume_batch(out,model_factory=lambda p:Repair())['status'],'finished')

    def test_comparison_original_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'repeat-1-on'
            comparison=root/'comparison.json';comparison.write_text('{"original":true}')
            with self.assertRaises(KeyboardInterrupt):evaluate('benchmarks',out,Crash,task_id='addition')
            resume_batch(out,model_factory=lambda p:Repair())
            self.assertEqual(comparison.read_text(),'{"original":true}')
            self.assertTrue((root/'resume-notice.json').exists())

    def test_no_budget_remains_does_not_call_model(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'batch'
            evaluate('benchmarks',out,Repair,task_id='addition',max_steps=1)
            result=resume_batch(out,model_factory=lambda p:self.fail('No steps remain'))
            self.assertEqual(result['tasks'][0]['status'],'blocked')
            self.assertEqual(resume_batch(out,max_steps=10,model_factory=lambda p:Repair())['status'],'finished')

    def test_process_lock_rejects_second_resume_and_releases_after_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'batch'
            evaluate('benchmarks',out,Repair,task_id='addition')
            state=out/'addition/state.sqlite'
            code="from fixlab.locking import exclusive; import sys;\nwith exclusive(sys.argv[1],sys.argv[2]):\n print('locked',flush=True)\n sys.stdin.read()\n"
            for target,kind in ((out,'batch'),(state,'task'),(out/'addition/workspace','workspace')):
                proc=subprocess.Popen([sys.executable,'-c',code,str(target),kind],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
                try:
                    self.assertEqual(proc.stdout.readline().strip(),'locked')
                    with self.assertRaises(BusyError):
                        with exclusive(target,kind): pass
                    if kind in ('batch','task'):
                        with self.assertRaises(BusyError):resume_task(state,model_factory=lambda p:self.fail('busy'))
                    else:
                        other_state=Path(folder)/'other/state.sqlite'
                        with self.assertRaises(BusyError):
                            run_evaluated(Workspace(target),Repair(),'fix',other_state)
                        self.assertFalse(other_state.exists())
                finally:
                    proc.kill();proc.wait(timeout=10);proc.stdin.close();proc.stdout.close()
                with exclusive(target,kind): pass

    def test_cli_inspect_does_not_load_api_config(self):
        from fixlab.cli import main
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'batch'
            evaluate('benchmarks',out,Repair,task_id='addition')
            with patch('sys.argv',['fixlab','resume-batch',str(out),'--inspect']),patch('builtins.print'), \
                 patch('fixlab.batch_resume.load_config',side_effect=AssertionError('No API')), \
                 patch('fixlab.resume.load_config',side_effect=AssertionError('No API')):
                main()

    def test_tampered_snapshot_is_blocked_before_workspace_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'batch';models=iter([Crash(),Repair(),Repair()])
            with self.assertRaises(KeyboardInterrupt):evaluate(self.suite(root),out,lambda:next(models))
            path=out/'batch-plan.json';plan=json.loads(path.read_text())
            plan['tasks'][1]['task']='tampered'
            path.write_text(json.dumps(plan))
            result=resume_batch(out,model_factory=lambda p:Repair())
            self.assertEqual(result['tasks'][1]['status'],'blocked')
            self.assertFalse((out/'b').exists())
            self.assertEqual(result['tasks'][2]['agent_status'],'completed')

    def test_provider_error_is_redacted_and_other_tasks_continue(self):
        class Offline(Repair):
            def reply(self,messages):raise ConnectionError('private-provider-message')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'batch';models=iter([Crash(),Repair(),Repair()])
            with self.assertRaises(KeyboardInterrupt):evaluate(self.suite(root),out,lambda:next(models))
            models=iter([Offline(),Repair(),Repair()])
            result=resume_batch(out,model_factory=lambda p:next(models))
            self.assertEqual(result['tasks'][0]['status'],'error')
            self.assertNotIn('private-provider-message',Path(result['log']).read_text())
            self.assertEqual(json.loads((out/'summary.json').read_text())['successes'],2)
