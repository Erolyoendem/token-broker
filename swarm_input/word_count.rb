def word_count(text)
  counts = Hash.new(0)
  text.downcase.split.each { |w| counts[w] += 1 }
  counts
end

text = "the quick brown fox jumps over the lazy dog the fox"
word_count(text).sort_by { |_, v| -v }.first(5).each do |word, count|
  puts "#{word}: #{count}"
end
