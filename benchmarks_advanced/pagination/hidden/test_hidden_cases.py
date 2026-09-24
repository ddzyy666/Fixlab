import unittest
from catalog import list_page
class Tests(unittest.TestCase):
    def test_0(self):
        self.assertEqual(list_page([1,2,3],2,2),[3])
    def test_1(self):
        self.assertEqual(list_page([],1,2),[])
    def test_2(self):
        self.assertEqual(list_page([1],9,2),[])
    def test_3(self):
        with self.assertRaises(ValueError): list_page([1],0,2)
    def test_4(self):
        with self.assertRaises(ValueError): list_page([1],1,0)
    def test_5(self):
        with self.assertRaises(ValueError): list_page([1],True,2)
    def test_6(self):
        with self.assertRaises(ValueError): list_page([1],1.5,2)
