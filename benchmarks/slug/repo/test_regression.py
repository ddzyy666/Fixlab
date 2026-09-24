import unittest
from text import slug
class RegressionTests(unittest.TestCase):
    def test_case_0(self):
        self.assertEqual(slug(" Hello   World "),"hello-world")
    def test_case_1(self):
        self.assertEqual(slug("a\tb"),"a-b")
    def test_case_2(self):
        self.assertEqual(slug(""),"")
