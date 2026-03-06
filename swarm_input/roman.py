def to_roman(num):
    values = [[1000,'M'],[900,'CM'],[500,'D'],[400,'CD'],[100,'C'], 
              [90,'XC'],[50,'L'],[40,'XL'],[10,'X'],[9,'IX'], 
              [5,'V'],[4,'IV'],[1,'I']]
    result = ''
    for v, s in values:
        while num >= v:
            result += s
            num -= v
    return result

for n in [1, 4, 9, 14, 40, 90, 399, 2024]:
    print(f"{n} => {to_roman(n)}")
