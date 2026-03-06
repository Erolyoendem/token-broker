class BankAccount
  attr_reader :balance, :owner
  def initialize(owner, balance = 0)
    @owner = owner; @balance = balance; @transactions = []
  end
  def deposit(amount)
    raise ArgumentError, "Amount must be positive" unless amount > 0
    @balance += amount; @transactions << { type: :deposit, amount: amount }
  end
  def withdraw(amount)
    raise ArgumentError, "Insufficient funds" if amount > @balance
    @balance -= amount; @transactions << { type: :withdrawal, amount: amount }
  end
  def statement
    @transactions.map { |t| "#{t[:type]}: #{t[:amount]}" }.join("\n")
  end
end

acc = BankAccount.new("Alice", 100)
acc.deposit(50); acc.withdraw(30)
puts acc.balance
puts acc.statement
