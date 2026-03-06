class Greeter
  def initialize(name)
    @name = name
  end

  def greet
    puts "Hello, #{@name}!"
  end
end

g = Greeter.new("TokenBroker")
g.greet
