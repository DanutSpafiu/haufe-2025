def bad_recursion(n):
    if n == 0:
        print("Done!")
    else:
        print(n)
        bad_recursion(n - 1)
    bad_recursion(n - 1)