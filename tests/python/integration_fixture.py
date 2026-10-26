"""Real loopback HTTP challenge and authenticated bridge for Site integration tests."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from web_bridge.web.client import Bridge
from web_bridge.transport.http import BoundedHTTPServer, handler_factory
from web_bridge.security.oauth import OAuth
from web_bridge.app import Companion
import tempfile

class Challenge(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path=='/redirect':
            self.send_response(302);self.send_header('Location','http://off-scope.invalid/');self.end_headers();return
        self.send_response(200)
        if self.path=='/set': self.send_header('Set-Cookie','session=secret-session-value; Path=/; HttpOnly')
        self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(json.dumps({'path':self.path,'cookie_present':'session=' in self.headers.get('Cookie','')}).encode())
    def do_POST(self):
        data=self.rfile.read(int(self.headers.get('Content-Length','0')))
        self.send_response(200);self.send_header('Content-Type','text/plain');self.end_headers();self.wfile.write(data)

def main():
    challenge=ThreadingHTTPServer(('127.0.0.1',0),Challenge)
    threading.Thread(target=challenge.serve_forever,daemon=True).start()
    bridge=Bridge({'lab':f'http://127.0.0.1:{challenge.server_port}'},allow_private=True,min_interval=0)
    auth=OAuth('fixture-private-unused-pin-0000',public_url='https://fixture.trycloudflare.com')
    runtime=tempfile.TemporaryDirectory(prefix='web-bridge-fixture-')
    companion=Companion(bridge,runtime.name)
    server=BoundedHTTPServer(('127.0.0.1',0),handler_factory(companion,auth,set(),os.environ['FIXTURE_SERVICE_TOKEN']))
    print(json.dumps({'bridge_port':server.server_port,'challenge_port':challenge.server_port}),flush=True)
    server.serve_forever()

if __name__=='__main__': main()
