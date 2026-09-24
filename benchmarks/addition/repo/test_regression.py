import unittest
from calculator import add
class RegressionTests(unittest.TestCase):
    def test_case_0(self):
        self.assertEqual(add(2,3),5)
    def test_case_1(self):
        self.assertEqual(add(-2,2),0)
