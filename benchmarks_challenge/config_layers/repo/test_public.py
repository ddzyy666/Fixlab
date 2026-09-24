import unittest
from settings import load_settings
class Public(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(load_settings({}, {"workers":0})["workers"],0)
