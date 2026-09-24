from stock import take
def fulfill(stock, lines):
    for sku, qty in lines:
        take(stock, sku, qty)
    return len(lines)
