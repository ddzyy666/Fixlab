import io
import tempfile
import unittest
from pathlib import Path
from fixlab.test_output import summarize


class TestOutputTests(unittest.TestCase):
    def test_success_is_short_and_complete_log_preserved(self):
        data=b'x'*20000+b'\nRan 694 tests in 1.2s\n\nOK\n'
        with tempfile.TemporaryDirectory() as folder:
            result=summarize(io.BytesIO(data),0,Path(folder))
            self.assertIn('Ran 694',result['output'])
            self.assertLess(len(result['output']),100)
            self.assertEqual(Path(result['log_file']).read_bytes(),data)

    def test_failure_tail_preserves_error_and_marks_truncation(self):
        data=b'x'*20000+b'\nFAIL: test_case\nAssertionError: unexpected\nFAILED (failures=1)\n'
        result=summarize(io.BytesIO(data),1)
        self.assertIn('AssertionError',result['output'])
        self.assertTrue(result['output_truncated'])
        self.assertLessEqual(len(result['output']),6000)
