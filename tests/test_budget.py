import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fixlab.budget import Budget, BudgetExceeded, accounting, validate
from fixlab.core import APIModel, Store
from fixlab.benchmark import evaluate
from fixlab.resume import resume_task, inspect_resume


class Repair(APIModel):
    def __init__(self):
        super().__init__('fixture', 'unused', 'https://example.invalid', self_check=False)
    def reply(self, messages):
        if any(m['role'] == 'tool' for m in messages):
            return {'role': 'assistant', 'content': 'done'}, {'prompt_tokens': 2, 'completion_tokens': 1, 'total_tokens': 3}
        return {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'write', 'type': 'function', 'function': {'name': 'write_file',
             'arguments': json.dumps({'path': 'calculator.py', 'content': 'def add(a,b): return a+b\n'})}}]}, {
                'prompt_tokens': 6, 'completion_tokens': 4, 'total_tokens': 10}


class BudgetTests(unittest.TestCase):
    def test_token_stop_before_write_and_cumulative_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            summary = evaluate('benchmarks', Path(folder)/'eval', Repair, task_id='addition',
                               budget_options={'max_tokens': 10, 'input_price': 2, 'output_price': 4, 'currency': 'TEST'})
            row = summary['results'][0]
            self.assertEqual(row['budget_stop_reason'], 'max_tokens')
            self.assertEqual(row['changed_files'], [])
            self.assertFalse(row['repair_success'])
            self.assertIsNone(row['error_type'])
            self.assertEqual(inspect_resume(row['state'])['budget']['max_tokens'], 10)
            stopped = resume_task(row['state'], model_factory=lambda p: Repair())
            self.assertEqual(stopped['tokens']['total_tokens'], 10)
            resumed = resume_task(row['state'], model_factory=lambda p: Repair(), budget_options={'max_tokens': 30})
            self.assertTrue(resumed['repair_success'])
            self.assertEqual(resumed['tokens']['total_tokens'], 13)
            self.assertAlmostEqual(resumed['cost']['estimated_amount'], 0.000036)
            self.assertTrue(resumed['cost']['complete'])
            self.assertEqual(resumed['budget']['input_price'], 2)
            store = Store(row['state'])
            try:
                self.assertEqual(sum(k == 'tool_started' for k,p in store.events()), 1)
            finally:
                store.db.close()

    def test_time_limit_counts_previous_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder)/'state.sqlite')
            try:
                store.add('execution_seconds', 7)
                with patch('fixlab.budget.time.monotonic', side_effect=[100, 103]):
                    budget = Budget(store, {'max_seconds': 10})
                    with self.assertRaisesRegex(BudgetExceeded, 'max_seconds'): budget.check()
            finally: store.db.close()

    def test_unknown_usage_stops_token_limited_task(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder)/'state.sqlite')
            try:
                store.add('usage', {})
                with self.assertRaisesRegex(BudgetExceeded, 'token_usage_unknown'):
                    Budget(store, {'max_tokens': 10}).check()
            finally: store.db.close()

    def test_failed_request_stops_retry_when_token_budget_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder)/'state.sqlite')
            model = APIModel('fixture', 'unused', 'https://example.invalid')
            model.on_retry = lambda payload: store.add('api_retry', payload)
            model.before_request = Budget(store, {'max_tokens': 100}).check
            try:
                with patch.object(model, '_reply_once', side_effect=TimeoutError), patch('fixlab.core.time.sleep'):
                    with self.assertRaisesRegex(BudgetExceeded, 'token_usage_unknown'): model.reply([])
            finally: store.db.close()

    def test_incomplete_cost_is_labeled(self):
        events = [('usage', {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}), ('api_retry', {})]
        cost = accounting(events, {'input_price': 1, 'output_price': 2, 'currency': 'TEST'})['cost']
        self.assertFalse(cost['complete'])
        self.assertAlmostEqual(cost['estimated_amount'], 0.00002)
        self.assertIsNone(accounting(events, {})['cost'])

    def test_invalid_options(self):
        for options in ({'max_tokens': 0}, {'max_tokens': 1.5}, {'max_seconds': float('nan')},
                        {'max_seconds': -1}, {'input_price': 1},
                        {'input_price': 1, 'output_price': 2}, {'output_price': -2}):
            with self.subTest(options=options), self.assertRaises(ValueError): validate(options)

    def test_expired_time_saves_report_without_model_call(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(Repair, 'reply', side_effect=AssertionError('Must not call API')):
                summary = evaluate('benchmarks', Path(folder)/'eval', Repair, task_id='addition',
                                   budget_options={'max_seconds': 1e-12})
            row = summary['results'][0]
            self.assertEqual(row['budget_stop_reason'], 'max_seconds')
            self.assertEqual(row['execution_status'], 'budget_exhausted')
            self.assertIsNone(row['error_type'])
            self.assertTrue((Path(row['artifacts'])/'report.json').exists())

    def test_cli_passes_budget_to_evaluation(self):
        from fixlab.cli import main
        with patch('sys.argv', ['fixlab', 'evaluate', '--max-tokens', '500', '--max-seconds', '60']), \
             patch('fixlab.cli.load_config', return_value={}), \
             patch('fixlab.cli.evaluate', return_value={}) as evaluator, patch('builtins.print'):
            main()
        self.assertEqual(evaluator.call_args.kwargs['budget_options'], {'max_tokens': 500, 'max_seconds': 60.0})
