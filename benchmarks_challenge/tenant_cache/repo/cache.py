class Cache:
    def __init__(self): self.entries={}
    def get(self,key,now):
        if key not in self.entries: return None
        expiry,value=self.entries[key]
        if now>expiry: return None
        return value
    def put(self,key,value,now,ttl): self.entries[key]=(now+ttl,value)
