import unittest
from checkout import total
class Tests(unittest.TestCase):
    def test_0(self):
        self.assertEqual(total(["10.00"],"0"),"10.00")
