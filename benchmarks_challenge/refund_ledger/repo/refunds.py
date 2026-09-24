from amounts import valid_amount
def refund(orders,ledger,order_id,request_id,amount):
    valid_amount(amount)
    order=orders[order_id]
    order["refunded"]=amount
    if amount>order["paid"]: raise ValueError("excess")
    entry={"order_id":order_id,"amount":amount,"refunded_total":amount}
    ledger[request_id]=entry
    return entry
