class Calculator
  def initialize
    @history = []
  end

  def add(a, b)
    result = a + b
    @history << "#{a} + #{b} = #{result}"
    result
  end

  def subtract(a, b)
    result = a - b
    @history << "#{a} - #{b} = #{result}"
    result
  end

  def multiply(a, b)
    result = a * b
    @history << "#{a} * #{b} = #{result}"
    result
  end

  def history
    @history
  end
end

calc = Calculator.new
puts calc.add(10, 5)
puts calc.subtract(10, 3)
puts calc.multiply(4, 7)
puts calc.history.inspect
