class FormalGreeter
  TITLES = { en: "Mr.", de: "Herr", fr: "M." }
  def initialize(lang = :en); @lang = lang; end
  def greet(name)
    title = TITLES.fetch(@lang, "")
    puts "Hello, #{title} #{name}!"
  end
end

[:en, :de, :fr].each do |lang|
  FormalGreeter.new(lang).greet("Smith")
end
