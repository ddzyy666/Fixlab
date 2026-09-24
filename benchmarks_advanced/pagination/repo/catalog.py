from paging import bounds
def list_page(items, page, size):
    start, end = bounds(page, size)
    return items[start:end]
