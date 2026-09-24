class Service:
    def __init__(self,cache,loader,clock,ttl=10):
        self.cache,self.loader,self.clock,self.ttl=cache,loader,clock,ttl
    def fetch(self,tenant,user_id):
        key=user_id
        value=self.cache.get(key,self.clock())
        if not value:
            value=self.loader(tenant,user_id)
            self.cache.put(key,value,self.clock(),self.ttl)
        return value
