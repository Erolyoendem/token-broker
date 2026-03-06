import json
from urllib.parse import urljoin, urlencode
from http.client import HTTPSConnection, HTTPConnection
from dataclasses import dataclass

@dataclass
class Response:
    status: int
    body: dict
    ok: bool

class ApiClient:
    DEFAULT_TIMEOUT = 30

    def __init__(self, base_url, api_key=None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {'Content-Type': 'application/json'}
        if api_key:
            self.headers['Authorization'] = f"Bearer {api_key}"

    def get(self, path, params=None):
        if params is None:
            params = {}
        uri = self.build_uri(path, params)
        return self.execute(uri, 'GET')

    def post(self, path, body=None):
        if body is None:
            body = {}
        uri = self.build_uri(path)
        return self.execute(uri, 'POST', body=json.dumps(body))

    def delete(self, path):
        uri = self.build_uri(path)
        return self.execute(uri, 'DELETE')

    def build_uri(self, path, params=None):
        if params is None:
            params = {}
        uri = urljoin(self.base_url, path)
        if params:
            uri += '?' + urlencode(params)
        return uri

    def execute(self, uri, method, body=None):
        try:
            if uri.startswith('https'):
                conn = HTTPSConnection(uri.split('://')[-1].split('/')[0], timeout=self.DEFAULT_TIMEOUT)
            else:
                conn = HTTPConnection(uri.split('://')[-1].split('/')[0], timeout=self.DEFAULT_TIMEOUT)
            conn.request(method, uri.split('://')[-1], headers=self.headers, body=body)
            response = conn.getresponse()
            body = json.loads(response.read())
            return Response(response.status, body, response.status < 400)
        except Exception as e:
            return Response(0, {'error': str(e)}, False)
        finally:
            if 'conn' in locals():
                conn.close()

client = ApiClient('https://api.example.com', api_key='secret')
result = client.get('/users', params={'page': 1, 'limit': 10})
print(result.status)
print(result.ok)
