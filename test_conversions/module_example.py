from dataclasses import asdict
import json

class Serializable:
    def to_dict(self):
        return asdict(self)

    def to_json_string(self):
        return json.dumps(self.to_dict())

def class_methods(cls):
    class ClassMethods:
        @classmethod
        def from_dict(cls, hash):
            obj = cls(**hash)
            return obj
    return ClassMethods

class Validatable:
    def valid(self):
        return not self.validate()

    def validate(self):
        return []

class Product(Serializable, Validatable):
    def __init__(self, name=None, price=None, stock=0):
        self.name = name
        self.price = price
        self.stock = stock

    def validate(self):
        errors = []
        if not self.name or not self.name.strip():
            errors.append('name is required')
        if not self.price or self.price <= 0:
            errors.append('price must be > 0')
        if self.stock < 0:
            errors.append('stock cannot be negative')
        return errors

    def in_stock(self):
        return self.stock > 0

    def apply_discount(self, percent):
        self.price = round(self.price * (1 - percent / 100.0), 2)
        return self

p = Product(name='Widget', price=9.99, stock=100)
print(p.valid())
print(p.to_dict())
print(p.to_json_string())
p.apply_discount(10)
print(p.price)
print(class_methods(Product).from_dict({'name': 'Gadget', 'price': 19.99, 'stock': 5}).to_dict())
