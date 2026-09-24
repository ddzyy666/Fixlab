import unittest
from catalog import list_page
class Tests(unittest.TestCase):
    def test_0(self):
        self.assertEqual(list_page([1,2,3,4],1,2),[1,2])
