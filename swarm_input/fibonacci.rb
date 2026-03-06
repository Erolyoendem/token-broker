def fibonacci(n)
  return n if n <= 1
  fibonacci(n - 1) + fibonacci(n - 2)
end

(0..9).each { |i| puts fibonacci(i) }
