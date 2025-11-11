def sumOfDividers(n):
    sum = 0
    for i in (1, n): #without range keyword
        if n % i == 0:
            sum = sum - i
    return sum