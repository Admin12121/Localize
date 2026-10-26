"""Authenticated bounded HTTP MCP listener."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import threading
from web_bridge.security.oauth import SCOPE
from web_bridge.transport.rpc import rpc, VERSION

def handler_factory(bridge, auth, allowed_origins, service_token=None):
    from urllib.parse import parse_qs, urlsplit
    class MCPHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Do not log bearer tokens, URL query strings, or entered pairing credentials.
            pass  # No request paths, bodies, cookies, or tokens in logs.

        def setup(self):
            super().setup()
            self.connection.settimeout(95)

        def _response(self, code, obj=None, content_type="application/json", headers=None):
            if isinstance(obj, (dict, list)):
                data = json.dumps(obj).encode("utf-8")
            elif isinstance(obj, str):
                data = obj.encode("utf-8")
            else:
                data = b""
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if data:
                self.wfile.write(data)

        def _form(self):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 20_000:
                    raise ValueError('Invalid input size')
                raw = self.rfile.read(length)
                if 'application/json' in self.headers.get('Content-Type',''):
                    obj = json.loads(raw)
                    if not isinstance(obj, dict): raise ValueError('Object required')
                    return obj
                if 'application/x-www-form-urlencoded' not in self.headers.get('Content-Type', ''):
                    raise ValueError('Unsupported content type')
                return {k: v[0] for k, v in parse_qs(raw.decode('utf-8'), keep_blank_values=True).items()}
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError('Malformed body') from exc

        def _auth(self):
            origin = self.headers.get("Origin")
            if origin and origin not in allowed_origins:
                self._response(403, {"error": "Origin not allowed"})
                return False
            raw_auth = self.headers.get('Authorization', '')
            machine_authenticated = bool(service_token and hmac.compare_digest(raw_auth, 'Bearer ' + service_token))
            if not machine_authenticated and not auth.check(raw_auth):
                resource_url = auth.base + '/.well-known/oauth-protected-resource'
                header = 'Bearer resource_metadata="' + resource_url + '", scope="' + SCOPE + '", error="invalid_token", error_description="Please authorize the CTF Bridge"'
                self._response(401, {"error": "authentication_required"}, headers={"WWW-Authenticate": header})
                return False
            return True

        def do_GET(self):
            path = urlsplit(self.path).path
            try:
                if path == '/health':
                    return self._response(200, {"ok": True, "version": VERSION})
                if path in ('/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp'):
                    return self._response(200, auth.protected())
                if path in ('/.well-known/oauth-authorization-server', '/.well-known/openid-configuration'):
                    return self._response(200, auth.discovery())
                if path == '/authorize':
                    args = {k:v[0] for k,v in parse_qs(urlsplit(self.path).query, keep_blank_values=True).items()}
                    ticket = auth.authorize(args)
                    return self._response(200, auth.login_html(ticket), 'text/html; charset=utf-8', {'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"})
                if path == '/mcp':
                    if not self._auth(): return
                    return self._response(405, {"error":"GET/SSE unsupported; use POST"})
                return self._response(404)
            except ValueError as exc:
                return self._response(400, {"error":str(exc)})

        def do_POST(self):
            path = urlsplit(self.path).path
            try:
                if path == '/register':
                    result = auth.register(self._form())
                    return self._response(201, result)
                if path == '/authorize':
                    args = self._form()
                    url = auth.approve(args.get('ticket',''), args.get('pin',''), self.client_address[0])
                    return self._response(302, headers={'Location':url})
                if path == '/token':
                    result = auth.exchange(self._form())
                    return self._response(200, result)
                if path != '/mcp':
                    return self._response(404)
                if not self._auth(): return
                if 'application/json' not in self.headers.get('Content-Type',''):
                    return self._response(415, {'error':'application/json required'})
                accept = self.headers.get('Accept','')
                if 'application/json' not in accept or 'text/event-stream' not in accept:
                    return self._response(406, {'error':'Accept must include application/json and text/event-stream'})
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 1_450_000:
                    return self._response(413, {'error':'Invalid request size'})
                msg = json.loads(self.rfile.read(size))
                version = self.headers.get('MCP-Protocol-Version')
                if version and version not in ('2025-06-18', '2025-03-26', '2024-11-05'):
                    return self._response(400, {'error': 'Unsupported MCP protocol version'})
                result = rpc(msg, bridge)
                if result is None:
                    return self._response(202)
                return self._response(200,result)
            except (ValueError, json.JSONDecodeError) as exc:
                return self._response(400, {'error':str(exc)})
    return MCPHandler


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try: super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request, client_address)
        finally: self.slots.release()


