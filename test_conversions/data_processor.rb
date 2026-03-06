class DataProcessor
  def initialize(records)
    @records = records
  end

  def summary
    {
      total:   @records.length,
      average: average_value,
      max:     @records.map { |r| r[:value] }.max,
      min:     @records.map { |r| r[:value] }.min,
    }
  end

  def filter_by_category(category)
    @records.select { |r| r[:category] == category }
  end

  def group_by_category
    @records.group_by { |r| r[:category] }
  end

  def top_n(n)
    @records.sort_by { |r| -r[:value] }.first(n)
  end

  def transform
    @records.map do |r|
      {
        id:       r[:id],
        label:    r[:name].upcase,
        score:    (r[:value] * 1.1).round(2),
        category: r[:category],
      }
    end
  end

  def total_by_category
    group_by_category.transform_values do |items|
      items.sum { |r| r[:value] }
    end
  end

  private

  def average_value
    return 0.0 if @records.empty?
    (@records.sum { |r| r[:value] }.to_f / @records.length).round(2)
  end
end

records = [
  { id: 1, name: 'alpha',   value: 42,  category: 'A' },
  { id: 2, name: 'beta',    value: 17,  category: 'B' },
  { id: 3, name: 'gamma',   value: 95,  category: 'A' },
  { id: 4, name: 'delta',   value: 63,  category: 'B' },
  { id: 5, name: 'epsilon', value: 28,  category: 'A' },
]

dp = DataProcessor.new(records)
puts dp.summary.inspect
puts dp.filter_by_category('A').map { |r| r[:name] }.inspect
puts dp.top_n(3).map { |r| r[:name] }.inspect
puts dp.total_by_category.inspect
puts dp.transform.first.inspect
