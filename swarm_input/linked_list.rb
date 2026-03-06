class Node
  attr_accessor :value, :next_node
  def initialize(value); @value = value; @next_node = nil; end
end

class LinkedList
  def initialize; @head = nil; end
  def prepend(value); node = Node.new(value); node.next_node = @head; @head = node; end
  def to_a
    result, current = [], @head
    while current; result << current.value; current = current.next_node; end
    result
  end
end

ll = LinkedList.new
[3, 2, 1].each { |v| ll.prepend(v) }
puts ll.to_a.inspect
