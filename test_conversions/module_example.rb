module Serializable
  def to_dict
    instance_variables.each_with_object({}) do |var, hash|
      hash[var.to_s.delete('@')] = instance_variable_get(var)
    end
  end

  def to_json_string
    require 'json'
    to_dict.to_json
  end

  def self.included(base)
    base.extend(ClassMethods)
  end

  module ClassMethods
    def from_dict(hash)
      obj = allocate
      hash.each { |k, v| obj.instance_variable_set("@#{k}", v) }
      obj
    end
  end
end

module Validatable
  def valid?
    validate.empty?
  end

  def validate
    []
  end
end

class Product
  include Serializable
  include Validatable

  attr_accessor :name, :price, :stock

  def initialize(name:, price:, stock: 0)
    @name  = name
    @price = price
    @stock = stock
  end

  def validate
    errors = []
    errors << 'name is required'  if @name.nil? || @name.strip.empty?
    errors << 'price must be > 0' if @price.nil? || @price <= 0
    errors << 'stock cannot be negative' if @stock < 0
    errors
  end

  def in_stock?
    @stock > 0
  end

  def apply_discount(percent)
    @price = (@price * (1 - percent / 100.0)).round(2)
    self
  end
end

p = Product.new(name: 'Widget', price: 9.99, stock: 100)
puts p.valid?
puts p.to_dict.inspect
puts p.to_json_string
p.apply_discount(10)
puts p.price
puts Product.from_dict('name' => 'Gadget', 'price' => 19.99, 'stock' => 5).to_dict.inspect
