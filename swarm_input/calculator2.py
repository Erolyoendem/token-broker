import math

class ScientificCalculator:
    def square_root(self, n):
        return math.sqrt(n)

    def power(self, base, exp):
        return base ** exp

    def log(self, n):
        return math.log(n)

    def factorial(self, n):
        if n <= 1:
            return 1
        else:
            return n * self.factorial(n - 1)

calc = ScientificCalculator()
print(calc.square_root(16))
print(calc.power(2, 10))
print(calc.factorial(5))
