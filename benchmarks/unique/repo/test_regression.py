import unittest
from lists import unique
class RegressionTests(unittest.TestCase):
    def test_case_0(self):
        self.assertEqual(unique([3,1,3,2]),[3,1,2])
    def test_case_1(self):
        self.assertEqual(unique([]),[])
