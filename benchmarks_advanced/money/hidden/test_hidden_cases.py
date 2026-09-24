import unittest
from checkout import total
class Tests(unittest.TestCase):
    def test_0(self):
        self.assertEqual(total(["0.105"],"0"),"0.11")
    def test_1(self):
        self.assertEqual(total(["0.005","0.005"],"0"),"0.01")
    def test_2(self):
        self.assertEqual(total(["20","30"],"0.1"),"45.00")
    def test_3(self):
        self.assertEqual(total([],"0"),"0.00")
    def test_4(self):
        for value in ["-1","NaN","Infinity","bad"]:
            with self.assertRaises(ValueError): total([value],"0")
    def test_5(self):
        for rate in ["-0.1","1.1","NaN","Infinity","bad"]:
            with self.assertRaises(ValueError): total(["1"],rate)
