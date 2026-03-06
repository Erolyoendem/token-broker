class ScientificCalculator
  def square_root(n); Math.sqrt(n); end
  def power(base, exp); base ** exp; end
  def log(n); Math.log(n); end
  def factorial(n); n <= 1 ? 1 : n * factorial(n - 1); end
end

calc = ScientificCalculator.new
puts calc.square_root(16)
puts calc.power(2, 10)
puts calc.factorial(5)
