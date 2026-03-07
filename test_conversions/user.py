class User:
    def __init__(self, name, email, age):
        self.name = name
        self.email = email
        self.age = age

    def __str__(self):
        return f"User({self.name}, {self.email}, age={self.age})"

    @property
    def adult(self):
        return self.age >= 18

    @classmethod
    def create(cls, name, email, age):
        return cls(name, email, age)

u = User.create("Alice", "alice@example.com", 25)
print(u)
print(u.adult)
u.name = "Bob"
print(u.name)
