def take(stock, sku, qty):
    if stock.get(sku, 0) < qty: raise ValueError("insufficient")
    stock[sku] -= qty
