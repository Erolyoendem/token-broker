class Stack:
    def __init__(self):
        self.data = []

    def push(self, item):
        self.data.append(item)

    def pop(self):
        return self.data.pop()

    def peek(self):
        return self.data[-1]

    def is_empty(self):
        return len(self.data) == 0

    def size(self):
        return len(self.data)

s = Stack()
s.push(1)
s.push(2)
s.push(3)
print(s.peek())
print(s.pop())
print(s.size())
