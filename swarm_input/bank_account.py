class BankAccount:
    def __init__(self, owner, balance=0):
        self._owner = owner
        self._balance = balance
        self._transactions = []

    @property
    def balance(self):
        return self._balance

    @property
    def owner(self):
        return self._owner

    def deposit(self, amount):
        if amount <= 0:
            raise ValueError("Amount must be positive")
        self._balance += amount
        self._transactions.append({"type": "deposit", "amount": amount})

    def withdraw(self, amount):
        if amount > self._balance:
            raise ValueError("Insufficient funds")
        self._balance -= amount
        self._transactions.append({"type": "withdrawal", "amount": amount})

    def statement(self):
        return "\n".join(f"{t['type']}: {t['amount']}" for t in self._transactions)

acc = BankAccount("Alice", 100)
acc.deposit(50)
acc.withdraw(30)
print(acc.balance)
print(acc.statement)
