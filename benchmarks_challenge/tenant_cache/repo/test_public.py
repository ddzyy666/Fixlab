import unittest
from cache import Cache
from service import Service
class Public(unittest.TestCase):
    def test_tenant(self):
        s=Service(Cache(),lambda t,u:{"tenant":t},lambda:0)
        self.assertEqual(s.fetch("a",1),{"tenant":"a"})
        self.assertEqual(s.fetch("b",1),{"tenant":"b"})
