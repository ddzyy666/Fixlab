import unittest
from orders import fulfill
class Tests(unittest.TestCase):
    def test_0(self):
        stock={"a":5}; self.assertEqual(fulfill(stock,[("a",2)]),2); self.assertEqual(stock,{"a":3})
