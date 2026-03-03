import functools, operator
m = lambda s: functools.reduce(operator.xor, (ord(c) for c in s), 0)
d = {chr(i+65): m(chr(i+65)*3) for i in range(26)}
r = sorted(d.items(), key=lambda x: x[1], reverse=True)[:5]
print("|".join(f"{k}={v}" for k,v in r))
