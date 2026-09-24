from pricing import discounted
def invoice_total(prices, rate):
    return discounted(sum(prices), rate)
