require 'net/http'
require 'json'
require 'uri'

class ApiClient
  DEFAULT_TIMEOUT = 30

  def initialize(base_url, api_key: nil)
    @base_url = base_url.chomp('/')
    @api_key  = api_key
    @headers  = { 'Content-Type' => 'application/json' }
    @headers['Authorization'] = "Bearer #{@api_key}" if @api_key
  end

  def get(path, params: {})
    uri = build_uri(path, params)
    request = Net::HTTP::Get.new(uri)
    apply_headers(request)
    execute(uri, request)
  end

  def post(path, body: {})
    uri = build_uri(path)
    request = Net::HTTP::Post.new(uri)
    apply_headers(request)
    request.body = body.to_json
    execute(uri, request)
  end

  def delete(path)
    uri = build_uri(path)
    request = Net::HTTP::Delete.new(uri)
    apply_headers(request)
    execute(uri, request)
  end

  private

  def build_uri(path, params = {})
    uri = URI("#{@base_url}#{path}")
    uri.query = URI.encode_www_form(params) unless params.empty?
    uri
  end

  def apply_headers(request)
    @headers.each { |k, v| request[k] = v }
  end

  def execute(uri, request)
    Net::HTTP.start(uri.host, uri.port,
                    use_ssl: uri.scheme == 'https',
                    read_timeout: DEFAULT_TIMEOUT) do |http|
      response = http.request(request)
      {
        status: response.code.to_i,
        body:   JSON.parse(response.body, symbolize_names: true),
        ok:     response.code.to_i < 400
      }
    end
  rescue StandardError => e
    { status: 0, body: { error: e.message }, ok: false }
  end
end

client = ApiClient.new('https://api.example.com', api_key: 'secret')
result = client.get('/users', params: { page: 1, limit: 10 })
puts result[:status]
puts result[:ok]
