import unittest
from orders import fulfill
class Tests(unittest.TestCase):
    def test_0(self):
        stock={"a":5}; self.assertEqual(fulfill(stock,[("a",2),("a",3)]),5); self.assertEqual(stock,{"a":0})
    def test_1(self):
        stock={"a":2,"b":0}
        with self.assertRaises(ValueError): fulfill(stock,[("a",1),("b",1)])
        self.assertEqual(stock,{"a":2,"b":0})
    def test_2(self):
        stock={"a":3}
        with self.assertRaises(ValueError): fulfill(stock,[("a",2),("a",2)])
        self.assertEqual(stock,{"a":3})
    def test_3(self):
        for qty in [0,-1,True,1.5]:
            stock={"a":3}
            with self.assertRaises(ValueError): fulfill(stock,[("a",qty)])
            self.assertEqual(stock,{"a":3})
    def test_4(self):
        stock={"a":1}
        with self.assertRaises(ValueError): fulfill(stock,[("missing",1)])
        self.assertEqual(stock,{"a":1})
