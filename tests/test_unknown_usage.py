import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fixlab.budget import Budget, BudgetExceeded, accounting
from fixlab.core import APIModel, Store

class UnknownUsageTests(unittest.TestCase):
    def test_allow_preserves_unknown_usage_and_known_token_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'state.sqlite')
            try:
                store.add('usage', {'total_tokens': 10})
                store.add('api_retry', {'usage_unknown': True})
                with self.assertRaisesRegex(BudgetExceeded,'token_usage_unknown'):
                    Budget(store,{'max_tokens':20}).check()
                Budget(store,{'max_tokens':20,'unknown_usage':'allow'}).check()
                self.assertFalse(accounting(store.events(),{})['token_usage_complete'])
                with self.assertRaisesRegex(BudgetExceeded,'max_tokens'):
                    Budget(store,{'max_tokens':10,'unknown_usage':'allow'}).check()
            finally:store.db.close()

    def test_diagnostics_do_not_include_request_content_or_credentials(self):
        model=APIModel('fixture','secret-key','https://example.invalid')
        events=[];model.on_request=events.append
        response={'choices':[{'message':{'role':'assistant','content':'done'}}]}
        with patch('fixlab.core.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
            model.reply([{'role':'user','content':'private-source-code'}])
        self.assertEqual([e['phase'] for e in events],['started','finished'])
        self.assertGreater(events[-1]['request_bytes'],0)
        self.assertEqual(events[-1]['outcome'],'success')
        self.assertNotIn('secret-key',json.dumps(events))
        self.assertNotIn('private-source-code',json.dumps(events))
        with patch('fixlab.core.urllib.request.urlopen',side_effect=TimeoutError('private-error')):
            with self.assertRaises(TimeoutError):model._reply_once([])
        self.assertEqual(events[-1]['error_type'],'TimeoutError')
        self.assertNotIn('private-error',json.dumps(events))
