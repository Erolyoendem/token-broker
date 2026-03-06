class Stack
  def initialize
    @data = []
  end
  def push(item); @data.push(item); end
  def pop; @data.pop; end
  def peek; @data.last; end
  def empty?; @data.empty?; end
  def size; @data.size; end
end

s = Stack.new
s.push(1); s.push(2); s.push(3)
puts s.peek
puts s.pop
puts s.size
