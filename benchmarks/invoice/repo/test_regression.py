import unittest
from invoice import invoice_total
class RegressionTests(unittest.TestCase):
    def test_case_0(self):
        self.assertEqual(invoice_total([20,30],0.1),45)
    def test_case_1(self):
        self.assertEqual(invoice_total([10],0),10)
    def test_case_2(self):
        self.assertEqual(invoice_total([],0.5),0)
