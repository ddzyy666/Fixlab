from money import parse
def total(prices, discount):
    return str(round(sum(parse(p) for p in prices) * (1-parse(discount)),2))
