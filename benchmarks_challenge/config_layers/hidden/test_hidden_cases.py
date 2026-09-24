import unittest
from copy import deepcopy
from merge import resolve
from settings import load_settings, DEFAULTS
class Hidden(unittest.TestCase):
    def test_nested_precedence(self):
        self.assertEqual(resolve({"db":{"host":"a","port":1}}, {"db":{"host":"b"}}, {"db":{"port":2}}), {"db":{"host":"b","port":2}})
    def test_false_and_empty(self):
        self.assertEqual(resolve({"x":True,"y":[1],"z":"x"},{},{"x":False,"y":[],"z":""}),{"x":False,"y":[],"z":""})
    def test_none_inherits(self):
        self.assertEqual(resolve({"a":1},{"a":2},{"a":None,"missing":None}),{"a":2})
    def test_type_replacement(self):
        self.assertEqual(resolve({"x":{"a":1}},{"x":[2]},{}),{"x":[2]})
        self.assertEqual(resolve({"x":1},{},{"x":{"a":2}}),{"x":{"a":2}})
    def test_inputs_not_mutated(self):
        a={"x":{"v":[1]}}; b={"y":[2]}; c={"x":{"z":3}}; before=deepcopy((a,b,c))
        resolve(a,b,c)
        self.assertEqual((a,b,c),before)
    def test_result_has_no_aliases(self):
        a={"x":{"v":[1]}}; b={"y":[2]}; c={"z":{"k":[3]}}
        r=resolve(a,b,c); r["x"]["v"].append(9);r["y"].append(9);r["z"]["k"].append(9)
        self.assertEqual(a,{"x":{"v":[1]}});self.assertEqual(b,{"y":[2]});self.assertEqual(c,{"z":{"k":[3]}})
    def test_calls_are_independent(self):
        original=deepcopy(DEFAULTS)
        r=load_settings({"logging":{"level":"debug"}},{});r["tags"].append("changed")
        self.assertEqual(DEFAULTS,original)
        self.assertEqual(load_settings({},{}),original)
