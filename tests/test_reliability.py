import http.client
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from fixlab.core import APIModel, Store, Workspace, run


class ReliabilityTests(unittest.TestCase):
    def test_disconnect_retries_without_replaying_tools(self):
        model = APIModel('test', 'unused', 'https://example.invalid')
        events = []
        model.on_retry = events.append
        response = ({'role':'assistant','content':'ok'}, {})
        with patch.object(model, '_reply_once', side_effect=[http.client.RemoteDisconnected(), response]) as call, patch('fixlab.core.time.sleep'):
            self.assertEqual(model.reply([]), response)
            self.assertEqual(call.call_count, 2)
        self.assertTrue(events[0]['usage_unknown'])

    def test_retry_limit_and_auth_failure(self):
        model = APIModel('test', 'unused', 'https://example.invalid')
        with patch.object(model, '_reply_once', side_effect=TimeoutError) as call, patch('fixlab.core.time.sleep'):
            with self.assertRaises(TimeoutError): model.reply([])
            self.assertEqual(call.call_count, 3)
        with patch.object(model, '_reply_once', side_effect=urllib.error.HTTPError('url',401,'unauthorized',{},None)) as call:
            with self.assertRaises(urllib.error.HTTPError): model.reply([])
            self.assertEqual(call.call_count, 1)

    def test_rejected_finish_can_resume_within_total_budget(self):
        class Model:
            def reply(self, messages):
                return {'role':'assistant','content':'Here is the proposed fix'}, {}
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder)/'state.sqlite')
            try:
                workspace = Workspace(folder)
                check = lambda: {'passed':False,'code_changed':False}
                self.assertEqual(run(store, workspace, Model(), 'fix', 1, check),'budget_exhausted')
                self.assertEqual(run(store, workspace, Model(), 'fix', 2, check),'budget_exhausted')
                events = store.events()
                self.assertEqual(sum(k=='completion_check' for k,p in events),2)
                self.assertFalse(any(k=='completed' for k,p in events))
            finally:
                store.db.close()

    def test_model_corrects_after_finish_rejection(self):
        class Model:
            def reply(self, messages):
                if messages[-1]['role']=='user' and 'completion check failed' in messages[-1]['content']:
                    return {'role':'assistant','content':None,'tool_calls':[{'id':'fix','type':'function','function':{'name':'write_file','arguments':json.dumps({'path':'a.py','content':'fixed'})}}]}, {}
                return {'role':'assistant','content':'done'}, {}
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'state.sqlite')
            try:
                result=run(store,Workspace(folder),Model(),'fix',4,lambda:{'passed':(Path(folder)/'a.py').exists()})
                self.assertEqual(result,'completed')
                self.assertEqual((Path(folder)/'a.py').read_text(),'fixed')
            finally: store.db.close()
