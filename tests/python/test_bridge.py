import importlib.util
import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

import web_bridge.web.client as m
from web_bridge.transport.rpc import rpc
from web_bridge.transport.http import handler_factory


class Challenge(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/':
            payload = b'<a href="/secret">go</a><!-- hint --><form action="/login" method="POST"><input name="user"></form>'
        elif self.path == '/set':
            self.send_response(200)
            self.send_header('Set-Cookie', 'session=abc123; Path=/')
            self.end_headers()
            self.wfile.write(b'ok')
            return
        elif self.path == '/echo':
            payload = self.headers.get('Cookie', '').encode()
        elif self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', 'http://unrelated.invalid/private')
            self.end_headers()
            return
        elif self.path == '/binary':
            self.send_response(200)
            self.send_header('content-type','application/octet-stream')
            self.end_headers()
            self.wfile.write(bytes(range(256)))
            return
        else:
            payload = b'notfound'
        self.send_response(200 if self.path in ['/', '/set', '/echo'] else 404)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        data = self.rfile.read(n)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def app():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Challenge)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bridge = m.Bridge({'lab': f'http://127.0.0.1:{server.server_port}'}, allow_private=True, min_interval=0)
    try:
        yield bridge
    finally:
        server.shutdown()
        server.server_close()


def test_requests_sessions_redirects_html(app):
    assert app.http_request('lab', path='/')['status'] == 200
    assert app.http_request('lab', path='/set')['status'] == 200
    assert 'session=[REDACTED]' in app.http_request('lab', path='/echo')['body_text']
    assert app.http_request('lab', path='/redirect')['status'] == 302
    html = app.inspect_html('lab')
    assert html['forms'][0]['inputs'][0]['name'] == 'user'
    assert html['links'][0]['href'] == '/secret'
    assert html['comments'] == [' hint ']
    assert app.session_cookies('lab')['cookies'][0]['name'] == 'session'
    assert 'abc123' not in json.dumps(app.session_cookies('lab'))
    app.reset_session('lab')
    assert app.http_request('lab', path='/echo')['body_text'] == ''


def test_batch_post_and_errors(app):
    results = app.http_batch('lab', [{'path': '/'}, {'method': 'POST', 'path': '/echo', 'body': 'hello'}])['results']
    assert len(results) == 2 and results[1]['body_text'] == 'hello'
    for path in ['//other.net', 'https://evil.invalid', '/\\evil']:
        with pytest.raises(m.BridgeError):
            app.http_request('lab', path=path)
    for header in ['Host', 'Transfer-Encoding', 'Proxy-Authorization']:
        with pytest.raises(m.BridgeError):
            app.http_request('lab', headers={header: 'other.net'})
    with pytest.raises(m.BridgeError):
        app.http_batch('lab', [{'path': '/'}] * 11)
    with pytest.raises(m.BridgeError):
        app.http_request('missing')
    with pytest.raises(m.BridgeError):
        app.http_request('lab', body_base64='$$')


def test_default_private_address_block():
    app = m.Bridge({'lab': 'http://127.0.0.1:43210'})
    with pytest.raises(m.BridgeError):
        app.http_request('lab')


def test_mcp_rpc(app):
    def rpc(method, params=None, mid=1):
        return rpc({'jsonrpc': '2.0', 'id': mid, 'method': method, 'params': params or {}}, app)
    assert rpc('initialize')['result']['serverInfo']['name'] == 'ctf-instance-bridge'
    tools = rpc('tools/list')['result']['tools']
    assert {'http_request', 'browser_action', 'inspect_html', 'http_batch', 'list_targets', 'reset_session', 'session_cookies', 'request_history'} <= {v['name'] for v in tools}
    args = {'name': 'http_request', 'arguments': {'target': 'lab', 'path': '/'}}
    assert json.loads(rpc('tools/call', args)['result']['content'][0]['text'])['status'] == 200
    assert rpc('tools/call', {'name':'unknown'})['result']['isError']
    assert rpc({'jsonrpc':'2.0', 'method':'notifications/initialized'}, app) is None


def test_authenticated_http_mcp(app):
    import base64, hashlib
    from urllib.parse import urlencode, parse_qs, urlsplit
    from web_bridge.security.oauth import OAuth
    auth = OAuth('PAIRING-PIN-PRIVATE-0123456789', public_url='https://bridge.example.test')
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_factory(app, auth, {'https://chatgpt.com'}))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        assert json.loads(urlopen(base + '/health').read())['ok'] is True
        meta = json.load(urlopen(base+'/.well-known/oauth-protected-resource'))
        assert meta['resource'] == 'https://bridge.example.test/mcp'
        disc = json.load(urlopen(base+'/.well-known/oauth-authorization-server'))
        assert disc['code_challenge_methods_supported'] == ['S256']
        req = json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list'}).encode()
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(base+'/mcp', data=req, headers=headers))
        assert exc.value.code == 401 and 'resource_metadata' in exc.value.headers['WWW-Authenticate']
        redirect = 'https://chatgpt.com/connector_platform_oauth_redirect'
        with pytest.raises(HTTPError):
            urlopen(Request(base+'/register', data=json.dumps({'redirect_uris':['https://evil.test/steal']}).encode(), headers={'Content-Type':'application/json'}))
        reg = json.load(urlopen(Request(base+'/register', data=json.dumps({'redirect_uris':[redirect]}).encode(), headers={'Content-Type':'application/json'})))
        verifier='V'*48
        vchallenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        args={'client_id':reg['client_id'],'redirect_uri':redirect,'response_type':'code','code_challenge':vchallenge,
              'code_challenge_method':'S256','resource':meta['resource'],'scope':'ctf:access','state':'abc'}
        # ChatGPT and other compliant clients can identify the resource by its origin.
        args['resource'] = 'https://bridge.example.test'
        login=urlopen(base+'/authorize?'+urlencode(args)).read().decode()
        assert 'CTF Instance Bridge' in login and 'password' in login
        import re
        ticket=re.search(r'name=\'ticket\' value=\'([^\']+)',login).group(1)
        class NoFollow(__import__('urllib.request').request.HTTPRedirectHandler):
            def redirect_request(self, *args): return None
        opener=__import__('urllib.request').request.build_opener(NoFollow())
        with pytest.raises(HTTPError) as e:
            opener.open(Request(base+'/authorize',data=urlencode({'ticket':ticket,'pin':'PAIRING-PIN-PRIVATE-0123456789'}).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'}))
        assert e.value.code == 302
        url=e.value.headers['Location']; parsed=urlsplit(url)
        assert parsed.netloc=='chatgpt.com' and parse_qs(parsed.query)['state']==['abc']
        code=parse_qs(parsed.query)['code'][0]
        token_args={'grant_type':'authorization_code','client_id':reg['client_id'],'redirect_uri':redirect,'code':code,'code_verifier':verifier,'resource':'https://bridge.example.test'}
        tok=json.load(urlopen(Request(base+'/token',data=urlencode(token_args).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'})))
        assert tok['token_type']=='Bearer'
        headers['Authorization']='Bearer '+tok['access_token']
        tools=json.load(urlopen(Request(base+'/mcp',data=req,headers=headers)))['result']['tools']
        assert len(tools)==27 and all(t['securitySchemes'][0]['type']=='oauth2' for t in tools)
        assert json.load(urlopen(base+'/.well-known/oauth-protected-resource/mcp'))['resource'] == meta['resource']
        headers['Origin']='https://evil.example'
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(base+'/mcp',data=req,headers=headers))
        assert exc.value.code==403
        refresh=json.load(urlopen(Request(base+'/token',data=urlencode({'grant_type':'refresh_token','client_id':reg['client_id'],
               'refresh_token':tok['refresh_token'],'resource':meta['resource']}).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'})))
        assert refresh['access_token']!=tok['access_token']
    finally:
        server.shutdown()
        server.server_close()


def test_origin_validation():
    for url in ['http://user@localhost', 'http://a.net/root', 'ftp://a.net', 'http://a.net?x=1']:
        with pytest.raises(m.BridgeError):
            m.Bridge({'bad': url})
