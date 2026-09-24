import unittest
from bounds import clamp
class RegressionTests(unittest.TestCase):
    def test_case_0(self):
        self.assertEqual(clamp(5,0,10),5)
    def test_case_1(self):
        self.assertEqual(clamp(-1,0,10),0)
    def test_case_2(self):
        self.assertEqual(clamp(20,0,10),10)
