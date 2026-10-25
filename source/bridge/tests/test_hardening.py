import base64
import hashlib
import json
import socket
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
from test_bridge import app,m

def test_encodings_binary_history_and_cookie_redaction(app):
    binary=app.http_request('lab',path='/binary')
    assert base64.b64decode(binary['body_base64'])==bytes(range(256))
    assert binary['body_text']==''
    result=app.http_request('lab',method='POST',body_base64=base64.b64encode(b'binary upload').decode())
    assert result['body_text']=='binary upload'
    assert result['body_sha256']==hashlib.sha256(b'binary upload').hexdigest()
    result=app.http_request('lab',method='POST',json_body={'query':'{ health }'})
    assert json.loads(result['body_text'])=={'query':'{ health }'}
    result=app.http_request('lab',method='POST',form={'message':'a & b'})
    assert result['body_text']=='message=a+%26+b'
    result=app.http_request('lab',method='POST',form={'field':'value'},files=[{'filename':'sample.txt','data_base64':base64.b64encode(b'uploaded file').decode()}])
    assert 'uploaded file' in result['body_text'] and 'sample.txt' in result['body_text']
    app.http_request('lab',path='/set')
    evidence=app.request_history('lab')
    assert len(evidence['entries'])==6
    assert 'abc123' not in json.dumps(evidence)
    assert '[REDACTED' in app.http_request('lab',path='/set')['headers']['Set-Cookie']
    for i in range(105):app._history['lab'].append({'index':i})
    assert app.request_history('lab',limit=100)['retained']==100

def test_dns_pinning_blocks_changes_and_avoids_second_lookup(app,monkeypatch):
    real=socket.getaddrinfo
    calls=[]
    def resolve(*args,**kwargs):calls.append(args);return real(*args,**kwargs)
    monkeypatch.setattr(socket,'getaddrinfo',resolve)
    assert app.http_request('lab')['status']==200
    assert len(calls)==1 # socket connects to validated numeric IP directly
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.2',80))])
    with pytest.raises(m.BridgeError,match='DNS changed'):app.http_request('lab')

def test_proxy_environment_does_not_change_route(app,monkeypatch):
    monkeypatch.setenv('http_proxy','http://127.0.0.1:1')
    monkeypatch.setenv('HTTP_PROXY','http://127.0.0.1:1')
    monkeypatch.setenv('no_proxy','')
    monkeypatch.setenv('NO_PROXY','')
    assert app.http_request('lab')['status']==200

def test_unsafe_upload_paths_headers_and_batch_target_changes(app):
    for path in ['//evil.test','/\\evil.test','/x#fragment','/x\x00']:
        with pytest.raises(m.BridgeError):app.http_request('lab',path=path)
    with pytest.raises(m.BridgeError):app.http_request('lab',files=[{'filename':'../../secret','data_base64':''}])
    with pytest.raises(m.BridgeError):app.http_request('lab',headers={'bad header':'x'})
    with pytest.raises(m.BridgeError):app.http_request('lab',body='x',json_body={})
    with pytest.raises(m.BridgeError):app.http_batch('lab',[{'target':'other'}])
    with pytest.raises(m.BridgeError):app.http_request('lab',timeout_seconds=float('nan'))

def test_machine_auth_and_origin_restrictions(app):
    import secrets,threading
    from http.server import ThreadingHTTPServer
    from oauth import OAuth
    token=secrets.token_urlsafe(48)
    server=ThreadingHTTPServer(('127.0.0.1',0),m.handler_factory(app,OAuth('private-test-pin-000000',public_url='https://fixture.trycloudflare.com'),{'https://chatgpt.com'},token))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        url=f'http://127.0.0.1:{server.server_port}/mcp';body=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'list_targets','arguments':{}}}).encode()
        headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
        with pytest.raises(HTTPError) as exc:urlopen(Request(url,data=body,headers=headers))
        assert exc.value.code==401
        headers['Authorization']='Bearer '+token
        assert json.load(urlopen(Request(url,data=body,headers=headers)))['result']['isError'] is False
        headers['Origin']='https://evil.test'
        with pytest.raises(HTTPError) as exc:urlopen(Request(url,data=body,headers=headers))
        assert exc.value.code==403
    finally:server.shutdown();server.server_close()
