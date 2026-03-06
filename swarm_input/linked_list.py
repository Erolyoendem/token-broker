class Node:
    def __init__(self, value):
        self.value = value
        self.next_node = None

class LinkedList:
    def __init__(self):
        self.head = None

    def prepend(self, value):
        node = Node(value)
        node.next_node = self.head
        self.head = node

    def to_a(self):
        result = []
        current = self.head
        while current:
            result.append(current.value)
            current = current.next_node
        return result

ll = LinkedList()
for v in [3, 2, 1]:
    ll.prepend(v)
print(ll.to_a())
