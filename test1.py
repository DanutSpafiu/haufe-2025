def bad_recursion(n):
    if n == 0:
        print("Done!")
    else:
        print(n)
        bad_recursion(n - 1)
    bad_recursion(n - 1)
    
def add_item(item, items=[]):
    items.append(item)
    return items

def wrong_find_prime_number(n):
    if n % 2 == 0:
        return True
    else:
        return False