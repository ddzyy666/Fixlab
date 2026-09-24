import unittest
from copy import deepcopy
from refunds import refund
class Hidden(unittest.TestCase):
    def state(self): return {"o":{"paid":100,"refunded":0,"status":"paid"}},{}
    def test_transitions(self):
        o,l=self.state();refund(o,l,"o","a",30);self.assertEqual(o["o"]["status"],"partially_refunded")
        refund(o,l,"o","b",70);self.assertEqual(o["o"]["status"],"refunded")
    def test_retry_preserves_original_result_after_later_refund(self):
        o,l=self.state();a=refund(o,l,"o","a",30);refund(o,l,"o","b",70);before=deepcopy((o,l))
        self.assertEqual(refund(o,l,"o","a",30),a);self.assertEqual((o,l),before)
    def test_conflict_is_atomic(self):
        o,l=self.state();refund(o,l,"o","a",20);before=deepcopy((o,l))
        for order,amount in [("o",30),("unknown",20)]:
            with self.assertRaises(ValueError):refund(o,l,order,"a",amount)
            self.assertEqual((o,l),before)
    def test_overrefund_is_atomic(self):
        o,l=self.state();refund(o,l,"o","a",60);before=deepcopy((o,l))
        with self.assertRaises(ValueError):refund(o,l,"o","b",50)
        self.assertEqual((o,l),before)
    def test_invalid_amount_is_atomic(self):
        for amount in [0,-1,True,1.5]:
            o,l=self.state();before=deepcopy((o,l))
            with self.assertRaises(ValueError):refund(o,l,"o","a",amount)
            self.assertEqual((o,l),before)
    def test_retry_bool_is_rejected(self):
        o,l=self.state();refund(o,l,"o","a",1);before=deepcopy((o,l))
        with self.assertRaises(ValueError):refund(o,l,"o","a",True)
        self.assertEqual((o,l),before)
    def test_unknown_and_cancelled(self):
        o,l=self.state();o["o"]["status"]="cancelled";before=deepcopy((o,l))
        for order in ["o","missing"]:
            with self.assertRaises(ValueError):refund(o,l,order,"a",1)
            self.assertEqual((o,l),before)
    def test_return_values_are_independent(self):
        o,l=self.state();r=refund(o,l,"o","a",20);r["amount"]=999
        r2=refund(o,l,"o","a",20);self.assertEqual(r2["amount"],20);r2["amount"]=555
        self.assertEqual(l["a"]["amount"],20)
