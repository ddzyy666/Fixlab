import unittest
from refunds import refund
class Public(unittest.TestCase):
    def test_accumulate(self):
        orders={"o":{"paid":100,"refunded":0,"status":"paid"}};ledger={}
        refund(orders,ledger,"o","a",20);refund(orders,ledger,"o","b",30)
        self.assertEqual(orders["o"]["refunded"],50)
