import unittest
from cache import Cache
from service import Service
class Hidden(unittest.TestCase):
    def test_exact_expiry(self):
        c=Cache();c.put("k",{"v":1},2,3)
        self.assertEqual(c.get("k",4),{"v":1});self.assertIsNone(c.get("k",5))
    def test_zero_ttl(self):
        c=Cache();c.put("k",{},1,0);self.assertIsNone(c.get("k",1))
    def test_hit_does_not_extend(self):
        c=Cache();c.put("k",{},0,10);self.assertEqual(c.get("k",9),{});self.assertIsNone(c.get("k",10))
    def test_empty_hit(self):
        calls=[];s=Service(Cache(),lambda t,u:(calls.append((t,u)) or {}),lambda:0)
        s.fetch("t",1);s.fetch("t",1);self.assertEqual(len(calls),1)
    def test_put_get_copies(self):
        c=Cache();v={"roles":["user"]};c.put("k",v,0,10);v["roles"].append("admin")
        r=c.get("k",0);r["roles"].append("root");self.assertEqual(c.get("k",0),{"roles":["user"]})
    def test_service_miss_and_hit_copies(self):
        source={"roles":["user"]};s=Service(Cache(),lambda t,u:source,lambda:0)
        s.fetch("t",1)["roles"].append("admin");source["roles"].append("owner")
        self.assertEqual(s.fetch("t",1),{"roles":["user"]})
    def test_loader_failure_not_cached(self):
        calls=[]
        def load(t,u):
            calls.append(1)
            if len(calls)==1: raise RuntimeError("offline")
            return {"ok":True}
        s=Service(Cache(),load,lambda:0)
        with self.assertRaises(RuntimeError):s.fetch("t",1)
        self.assertEqual(s.fetch("t",1),{"ok":True});self.assertEqual(len(calls),2)
    def test_user_and_tenant_keys(self):
        s=Service(Cache(),lambda t,u:{"key":(t,u)},lambda:0)
        for t,u in [("a",1),("a",2),("b",1)]: self.assertEqual(s.fetch(t,u),{"key":(t,u)})
