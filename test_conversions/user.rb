class User
  attr_accessor :name, :email, :age

  def initialize(name, email, age)
    @name = name
    @email = email
    @age = age
  end

  def adult?
    @age >= 18
  end

  def to_s
    "User(#{@name}, #{@email}, age=#{@age})"
  end

  def self.create(name, email, age)
    new(name, email, age)
  end
end

u = User.create("Alice", "alice@example.com", 25)
puts u
puts u.adult?
u.name = "Bob"
puts u.name
