#!/usr/bin/env python3
"""CTF Instance Bridge: allowlisted MCP HTTP/browser client, stdlib MCP transport."""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import queue
import hmac
import html.parser
import http.cookiejar
import json
import os
import re
import socket
import sys
import threading
import time
import hashlib
import ipaddress
import secrets
import ssl
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit, urlencode
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener, ProxyHandler
from network import PinnedHTTPHandler, PinnedHTTPSHandler

VERSION = "2.0.0"
from oauth import OAuth, SCOPE
MAX_BODY = 1_000_000
MAX_TEXT = 80_000
BLOCKED_HEADERS = {"host", "connection", "transfer-encoding", "content-length", "proxy-authorization", "proxy-connection", "upgrade", "accept-encoding"}


class BridgeError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HtmlSummary(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.forms, self.scripts, self.comments, self.current_form = [], [], [], [], None
        self.metadata, self.title, self._tag = [], '', ''

    def handle_starttag(self, tag, attrs):
        self._tag = tag
        attrs = dict(attrs)
        if tag == 'meta' and len(self.metadata) < 100:
            self.metadata.append(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append({"href": attrs["href"], "label": ""})
        if tag == "script":
            self.scripts.append({"src": attrs.get("src", "inline")})
        if tag == "form":
            self.current_form = {"action": attrs.get("action", ""), "method": attrs.get("method", "get"), "inputs": []}
            self.forms.append(self.current_form)
        if tag in ("input", "textarea", "select", "button") and self.current_form is not None:
            self.current_form["inputs"].append({k: attrs.get(k, "") for k in ("name", "type", "value", "id")})

    def handle_endtag(self, tag):
        self._tag = ''
        if tag == "form":
            self.current_form = None

    def handle_data(self, data):
        if self._tag == 'title': self.title += data[:500]
        if self._tag == 'a' and self.links: self.links[-1]['label'] += data[:200]
        if self._tag == 'script' and self.scripts and self.scripts[-1]['src'] == 'inline':
            self.scripts[-1]['text'] = self.scripts[-1].get('text', '') + data[:8000]

    def handle_comment(self, data):
        if len(self.comments) < 30:
            self.comments.append(data[:500])


class Bridge:
    def __init__(self, targets: dict[str, str], *, allow_private=False, min_interval=0.1):
        if not isinstance(targets, dict):
            raise BridgeError("CTF_TARGETS must be a JSON object of name: origin")
        self.targets: dict[str, str] = {}
        if len(targets) > 20: raise BridgeError('At most 20 approved targets are supported')
        for name, url in targets.items():
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
                raise BridgeError("Target name must be 1-40 alphanumeric characters, _ or -")
            if not isinstance(url, str) or len(url) > 300 or any(c.isspace() or ord(c) < 32 for c in url) or '\\' in url:
                raise BridgeError('Invalid approved origin')
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
                raise BridgeError(f"Invalid origin for {name}; use only scheme://host[:port]")
            try:
                _ = parsed.port
            except ValueError as exc:
                raise BridgeError(f"Bad port for {name}") from exc
            self.targets[name] = urlunsplit((parsed.scheme, parsed.netloc.lower(), "", "", ""))
        self.allow_private = allow_private
        self.min_interval = max(0.0, float(min_interval))
        self._opener = {}
        self._cookies = {}
        self._last_request = {}
        self._lock = threading.RLock()
        self._browser = None
        self._browser_pages = {}
        self._browser_queue = None
        self._pins = {}
        self._history = {name: deque(maxlen=100) for name in self.targets}
        self._browser_events = {}
        self._secret_values = set()
        self._browser_process = None

    @classmethod
    def from_env(cls):
        raw = os.getenv("CTF_TARGETS", "")
        config_path = os.getenv("CTF_CONFIG", "")
        if config_path:
            raw = Path(config_path).expanduser().read_text(encoding="utf-8")
        return cls(json.loads(raw or "{}"), allow_private=os.getenv("CTF_ALLOW_PRIVATE", "0") == "1",
                   min_interval=float(os.getenv("CTF_MIN_REQUEST_INTERVAL", "0.1")))

    def _origin(self, target):
        if getattr(self,'cancelled',lambda:False)():raise BridgeError('CTF access was revoked locally.')
        if target not in self.targets:
            raise BridgeError("Unknown target; list_targets first. Targets can only be configured by the server owner.")
        origin = self.targets[target]
        hostname = urlsplit(origin).hostname
        try:
            addresses = tuple(sorted({a[4][0] for a in socket.getaddrinfo(hostname, urlsplit(origin).port or (443 if origin.startswith('https:') else 80), type=socket.SOCK_STREAM)}))
        except OSError as exc:
            raise BridgeError("Target DNS lookup failed") from exc
        if not addresses or not self.allow_private and any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise BridgeError("Non-public destination rejected. Explicitly opt into a private lab on Linux.")
        with self._lock:
            pinned = self._pins.setdefault(target, addresses)
            if not set(addresses).issubset(pinned):
                raise BridgeError("Target DNS changed. Review the approved origin and restart the bridge to repin.")
        return origin

    def _url(self, target, path):
        origin = self._origin(target)
        if not isinstance(path, str) or len(path) > 8192 or not path.startswith("/") or path.startswith("//") or "\\" in path or '#' in path or any(ord(c) < 32 or ord(c) == 127 for c in path):
            raise BridgeError("Path must be a same-origin absolute path starting with one slash")
        url = origin + path
        p = urlsplit(url)
        if f"{p.scheme}://{p.netloc}" != origin:
            raise BridgeError("Cross-origin URLs are forbidden")
        return url

    def _session(self, target):
        with self._lock:
            if target not in self._opener:
                jar = http.cookiejar.CookieJar()
                self._cookies[target] = jar
                self._opener[target] = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar), NoRedirect(), PinnedHTTPHandler(self._pins[target]), PinnedHTTPSHandler(self._pins[target]))
            return self._opener[target]

    def list_targets(self):
        return {"targets": [{"name": k, "origin": v} for k, v in self.targets.items()], "count": len(self.targets)}

    def reset_session(self, target):
        self._origin(target)
        with self._lock:
            self._opener.pop(target, None)
            self._cookies.pop(target, None)
            self._last_request.pop(target, None)
        if self._browser_process is not None:
            self._browser_process.call(target, 'reset', '/', '', '', '')
        return {"target": target, "reset": True}

    def _redact(self, text):
        for jar in self._cookies.values():
            self._secret_values.update(c.value for c in jar if c.value)
        for secret in sorted(self._secret_values, key=len, reverse=True):
            text = text.replace(secret, '[REDACTED]')
        return text

    def _redact_tree(self, obj):
        if isinstance(obj, str): return self._redact(obj)
        if isinstance(obj, dict): return {k: self._redact_tree(v) for k,v in obj.items()}
        if isinstance(obj, list): return [self._redact_tree(v) for v in obj]
        return obj

    def request_history(self, target, limit=20):
        self._origin(target)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise BridgeError('History limit must be 1-100')
        return {'target': target, 'entries': list(self._history[target])[-limit:], 'retained': len(self._history[target])}

    def session_cookies(self, target):
        self._origin(target)
        self._session(target)
        with self._lock:
            return {"cookies": [{"name": c.name, "domain": c.domain, "path": c.path, "secure": c.secure, 'expires': c.expires, 'http_only': c.has_nonstandard_attr('HttpOnly')} for c in self._cookies[target]]}

    def http_request(self, target, method="GET", path="/", headers=None, body=None, body_base64=None, timeout_seconds=12, params=None, json_body=None, form=None, files=None):
        if params is not None:
            if not isinstance(params, dict) or len(params) > 100:
                raise BridgeError('Parameters must be an object with at most 100 fields')
            path += ('&' if '?' in path else '?') + urlencode(params, doseq=True)
        url = self._url(target, path)
        if not isinstance(method, str):
            raise BridgeError('HTTP method must be text')
        method = method.upper()
        if method not in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            raise BridgeError("Unsupported HTTP method")
        if sum(v is not None for v in (body, body_base64, json_body, form)) > 1 or files is not None and any(v is not None for v in (body, body_base64, json_body)):
            raise BridgeError('Choose one body encoding; multipart files can be combined with form fields')
        if not isinstance(headers or {}, dict) or len(headers or {}) > 50:
            raise BridgeError("Headers must be a JSON object with at most 50 keys")
        hdr = {"User-Agent": "CTF-Instance-Bridge/1.0", "Accept-Encoding": "identity"}
        for k, v in (headers or {}).items():
            if not isinstance(k, str) or not isinstance(v, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,100}", k) or len(v) > 8192 or k.lower() in BLOCKED_HEADERS or "\r" in k + v or "\n" in k + v or '\x00' in v:
                raise BridgeError(f"Unsafe header: {k}")
            hdr[k] = v
            if k.lower() in ('authorization', 'cookie', 'x-api-key') and v:
                self._secret_values.add(v)
                if k.lower() == 'authorization' and ' ' in v:
                    self._secret_values.add(v.split(' ', 1)[1])
        try:
            if files is not None:
                if not isinstance(files, list) or not 1 <= len(files) <= 5 or form is not None and not isinstance(form, dict):
                    raise BridgeError('Multipart supports up to 5 files and an optional form object')
                boundary = 'ctf-' + secrets.token_hex(16)
                chunks = []
                for name, value in (form or {}).items():
                    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name):
                        raise BridgeError('Unsafe form field name')
                    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
                for file in files:
                    if not isinstance(file, dict) or set(file) - {'field', 'filename', 'content_type', 'data_base64'}:
                        raise BridgeError('Invalid multipart file')
                    field, filename = file.get('field', 'file'), file.get('filename', 'upload.bin')
                    ct = file.get('content_type', 'application/octet-stream')
                    if not isinstance(field, str) or not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', field) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', filename) or not isinstance(ct, str) or not re.fullmatch(r'[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+', ct):
                        raise BridgeError('Unsafe upload filename, field, or content type')
                    blob = base64.b64decode(file.get('data_base64', ''), validate=True)
                    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\nContent-Type: {ct}\r\n\r\n'.encode() + blob + b'\r\n')
                payload = b''.join(chunks) + f'--{boundary}--\r\n'.encode()
                hdr['Content-Type'] = f'multipart/form-data; boundary={boundary}'
            elif json_body is not None:
                payload = json.dumps(json_body, ensure_ascii=False).encode()
                hdr.setdefault('Content-Type', 'application/json')
            elif form is not None:
                if not isinstance(form, dict) or len(form) > 100:
                    raise BridgeError('Form must be an object with at most 100 fields')
                payload = urlencode(form, doseq=True).encode()
                hdr.setdefault('Content-Type', 'application/x-www-form-urlencoded')
            else:
                payload = base64.b64decode(body_base64, validate=True) if body_base64 is not None else (body.encode("utf-8") if body is not None else None)
        except ValueError as exc:
            raise BridgeError("Invalid base64") from exc
        if payload is not None and len(payload) > MAX_BODY:
            raise BridgeError("Request body exceeds 1 MB")
        timeout_seconds = float(timeout_seconds)
        if not 0 < timeout_seconds <= 30 or isinstance(timeout_seconds, bool):
            raise BridgeError("Timeout must be from 0 to 30 seconds")
        req = Request(url, data=payload, headers=hdr, method=method)
        with self._lock:
            now = time.monotonic()
            delta = self.min_interval - (now - self._last_request.get(target, 0))
            if delta > 0:
                time.sleep(delta)
            self._last_request[target] = time.monotonic()
            opener = self._session(target)
            start = time.monotonic()
            try:
                response = opener.open(req, timeout=timeout_seconds)
            except HTTPError as err:
                response = err  # 3xx (redirects disabled) and 4xx/5xx are useful evidence
            except (URLError, TimeoutError, OSError) as err:
                return {"error": str(err), "url": url}
            try:
                chunks, length = [], 0
                while length <= MAX_BODY:
                    remaining = timeout_seconds - (time.monotonic() - start)
                    if remaining <= 0: raise TimeoutError('Response deadline exceeded')
                    try: response.fp.raw._sock.settimeout(remaining)
                    except AttributeError: pass
                    chunk = response.read1(min(65536, MAX_BODY + 1 - length))
                    if not chunk: break
                    chunks.append(chunk); length += len(chunk)
                data = b''.join(chunks)
                truncated = len(data) > MAX_BODY
                if truncated:
                    data = data[:MAX_BODY]
                hs = dict(response.headers.items())
                hs = {k: '[REDACTED: stored in target session]' if k.lower() == 'set-cookie' else v for k,v in hs.items()}
                ct = response.headers.get('Content-Type', '')
                charset = response.headers.get_content_charset() or "utf-8"
                textual = not ct or any(x in ct.lower() for x in ('text/', 'json', 'xml', 'javascript', 'html'))
                try: decoded = data[:MAX_TEXT].decode(charset, errors='replace') if textual else ''
                except LookupError: decoded = data[:MAX_TEXT].decode('utf-8', errors='replace') if textual else ''
                decoded = self._redact(decoded)
                evidence_id = secrets.token_hex(12)
                result = {"url": self._redact(url), "method": method, "status": response.status,
                        "elapsed_ms": round((time.monotonic() - start) * 1000),
                        "headers": {k: self._redact(v) for k, v in hs.items()}, "body_text": decoded,
                        "body_base64": base64.b64encode(data).decode('ascii') if not textual and not any(s.encode() in data for s in self._secret_values) else None,
                        "body_bytes": len(data), "truncated": truncated or textual and len(data) > MAX_TEXT,
                        'request_id': evidence_id, 'body_sha256': hashlib.sha256(data).hexdigest()}
                self._history[target].append({'request_id': evidence_id, 'timestamp': int(time.time()), 'method': method, 'url': self._redact(url), 'status': response.status, 'request_bytes': len(payload or b''), 'response_bytes': len(data), 'body_sha256': result['body_sha256'], 'elapsed_ms': result['elapsed_ms'], 'truncated': result['truncated']})
                return result
            finally:
                response.close()

    def http_batch(self, target, requests):
        if not isinstance(requests, list) or not 1 <= len(requests) <= 10:
            raise BridgeError("Provide between 1 and 10 requests")
        out = []
        deadline = time.monotonic() + 45
        for i, r in enumerate(requests):
            if getattr(self,'cancelled',lambda:False)():raise BridgeError('CTF access was revoked locally.')
            if not isinstance(r, dict):
                raise BridgeError("Each request must be an object")
            if 'target' in r:
                raise BridgeError('Batch items cannot change target')
            if time.monotonic() >= deadline: raise BridgeError('Batch time budget exceeded')
            r = dict(r)
            r['timeout_seconds'] = min(float(r.get('timeout_seconds', 12)), deadline - time.monotonic())
            item = self.http_request(target, **r)
            out.append({'index': i, **item})
            if len(json.dumps(out)) > 1_500_000: raise BridgeError('Batch output size exceeded; use individual requests')
        return {"results": out}

    def inspect_html(self, target, path="/"):
        result = self.http_request(target, path=path)
        if result.get("error"):
            return result
        parser = HtmlSummary()
        parser.feed(result["body_text"])
        return {"status": result["status"], "url": result["url"], "links": parser.links[:150],
                "forms": parser.forms[:30], "scripts": parser.scripts[:100], "comments": parser.comments,
                'title': parser.title, 'metadata': parser.metadata, 'request_id': result['request_id']}

    def browser_action(self, target, action="visit", path="/", selector="", value="", script=""):
        """Optional isolated Chromium worker. All Playwright calls run on the same thread."""
        self._origin(target)
        if action not in ("visit", "snapshot", "click", "fill", "press", "evaluate", "diagnostics"):
            raise BridgeError("Unknown browser action")
        if action in ("click", "fill", "press") and not selector:
            raise BridgeError("Browser selector is required")
        from browser_process import BrowserProcess
        with self._lock:
            if self._browser_process is None:
                self._browser_process = BrowserProcess(self.targets, self.allow_private, self.min_interval, dict(self._pins))
        return self._browser_process.call(target, action, path, selector, value, script)

    def _browser_route(self, route, target):
        """Mediate Chromium HTTP(S) through pinned direct connections; Chromium cannot choose DNS."""
        request = route.request
        events = self._browser_events[target]
        try:
            origin = self._origin(target)
            parsed = urlsplit(request.url)
            if parsed.scheme not in ('http', 'https') or f'{parsed.scheme}://{parsed.netloc}' != origin or parsed.username or parsed.password:
                raise BridgeError('Browser off-origin request blocked')
            headers = {k:v for k,v in request.headers.items() if k.lower() not in BLOCKED_HEADERS}
            headers['Accept-Encoding'] = 'identity'
            payload = request.post_data_buffer
            if payload and len(payload) > MAX_BODY: raise BridgeError('Browser upload exceeds 1 MB')
            opener = build_opener(ProxyHandler({}), NoRedirect(), PinnedHTTPHandler(self._pins[target]), PinnedHTTPSHandler(self._pins[target]))
            try: response = opener.open(Request(request.url, data=payload, headers=headers, method=request.method), timeout=12)
            except HTTPError as exc: response = exc
            try:
                data = response.read(MAX_BODY + 1)
                if len(data) > MAX_BODY: raise BridgeError('Browser response exceeds 1 MB')
                hs = {k:v for k,v in response.headers.items() if k.lower() not in ('content-length', 'transfer-encoding', 'connection')}
                route.fulfill(status=response.status, headers=hs, body=data)
                events.append({'type': 'network', 'method': request.method, 'url': request.url.split('?')[0], 'status': response.status, 'bytes': len(data)})
            finally: response.close()
        except Exception:
            events.append({'type': 'blocked_or_failed', 'method': request.method, 'url': request.url.split('?')[0]})
            route.abort()

    def _browser_loop(self):
        """A single thread owns Playwright to avoid sync API cross-thread failures."""
        pw, browser = None, None
        while True:
            future, target, action, path, selector, value, script = self._browser_queue.get()
            try:
                if action == 'reset':
                    page = self._browser_pages.pop(target, None)
                    if page: page.context.close()
                    self._browser_events.pop(target, None)
                    future.set_result({'reset': True})
                    continue
                if browser is None:
                    try:
                        from playwright.sync_api import sync_playwright
                    except ImportError as exc:
                        raise BridgeError("Install optional browser: pip install playwright && playwright install chromium") from exc
                    pw = sync_playwright().start()
                    browser = pw.chromium.launch(headless=True, chromium_sandbox=True, args=['--disable-quic', '--host-resolver-rules=MAP * ~NOTFOUND', '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
                if target not in self._browser_pages:
                    origin = self._origin(target)
                    ctx = browser.new_context(accept_downloads=False, service_workers="block")
                    ctx.add_init_script("for (const key of ['RTCPeerConnection','webkitRTCPeerConnection','WebTransport','Worker','SharedWorker']) Object.defineProperty(globalThis,key,{value:undefined,writable:false,configurable:false});")
                    self._browser_events[target] = deque(maxlen=100)
                    ctx.route('**/*', lambda route, request, target=target: self._browser_route(route, target))
                    if not hasattr(ctx, 'route_web_socket'):
                        ctx.close()
                        raise BridgeError('Playwright 1.48+ required to block unsupported WebSocket traffic')
                    ctx.route_web_socket('**/*', lambda ws: ws.close())
                    self._browser_pages[target] = ctx.new_page()
                    self._browser_pages[target].on('console', lambda msg, target=target: self._browser_events[target].append({'type': 'console', 'level': msg.type, 'text': msg.text[:2000]}))
                    self._browser_pages[target].on('pageerror', lambda err, target=target: self._browser_events[target].append({'type': 'pageerror', 'text': str(err)[:2000]}))
                page = self._browser_pages[target]
                page.set_default_timeout(12000)
                if action == "visit":
                    page.goto(self._url(target, path), wait_until="domcontentloaded", timeout=20000)
                elif action == "click":
                    page.locator(selector).first.click()
                elif action == "fill":
                    page.locator(selector).first.fill(value)
                elif action == "press":
                    page.locator(selector).first.press(value)
                elif action == "evaluate":
                    output = page.evaluate(script)
                    self._secret_values.update(c['value'] for c in page.context.cookies() if c.get('value'))
                    future.set_result({"url": page.url, "value": self._redact(json.dumps(output, ensure_ascii=False))[:MAX_TEXT]})
                    continue
                self._secret_values.update(c['value'] for c in page.context.cookies() if c.get('value'))
                result = {'url': page.url, 'events': list(self._browser_events[target])} if action == 'diagnostics' else {"url": page.url, "title": page.title(), "html": page.content()[:MAX_TEXT]}
                future.set_result(self._redact_tree(result))
            except Exception as exc:
                future.set_exception(BridgeError(f"Browser failed: {self._redact(str(exc))}"))



# The native Site and Linux bridge use one versioned tool contract.
TOOL_DEFINITIONS = json.loads((Path(__file__).resolve().parent.parent / 'BRIDGE_TOOLS.json').read_text(encoding='utf-8'))['tools']
SCHEMAS = {tool['name']: (tool['description'], tool['inputSchema']['properties'], tool['inputSchema'].get('required', [])) for tool in TOOL_DEFINITIONS}


def rpc(message, bridge):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None,
                "error": {"code": -32600, "message": "Invalid Request"}}
    if "id" not in message:
        return None
    req_id = message["id"]
    name = message.get("method")
    try:
        if name == "initialize":
            # Don't advertise an unknown newer protocol than the client's version
            client_protocol = message.get("params", {}).get("protocolVersion", "2025-03-26")
            protocol = client_protocol if client_protocol in ("2025-06-18", "2025-03-26", "2024-11-05") else "2025-06-18"
            data = {"protocolVersion": protocol, "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "ctf-instance-bridge", "version": VERSION}}
        elif name == "ping":
            data = {}
        elif name == "tools/list":
            data = {"tools": [{"name": k, "description": desc,
                               "inputSchema": {"type": "object", "properties": fields, "required": required, "additionalProperties": False},
                               "securitySchemes": [{"type": "oauth2", "scopes": [SCOPE]}]}
                              for k, (desc, fields, required) in SCHEMAS.items()]}
        elif name == "tools/call":
            params = message.get("params", {})
            tool = params.get("name")
            args = params.get("arguments") or {}
            if tool not in SCHEMAS:
                raise BridgeError("Unknown tool")
            if not isinstance(args, dict):
                raise BridgeError("arguments must be an object")
            allowed = set(SCHEMAS[tool][1])
            if set(args) - allowed:
                raise BridgeError("Unexpected argument(s): " + ",".join(sorted(set(args) - allowed)))
            missing = set(SCHEMAS[tool][2]) - set(args)
            if missing:
                raise BridgeError("Missing: " + ",".join(sorted(missing)))
            result = getattr(bridge, tool)(**args)
            data = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "isError": bool(result.get('error'))}
        else:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": req_id, "result": data}
    except Exception as exc:
        if name == "tools/call":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True}}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(exc)}}


def serve_stdio(bridge):
    for line in sys.stdin:
        try:
            message = json.loads(line)
            result = rpc(message, bridge)
            if result is not None:
                sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            print(f"MCP error: {exc}", file=sys.stderr)


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


def main():
    parser = argparse.ArgumentParser(description="MCP bridge for authorized live web CTF challenges")
    parser.add_argument("transport", choices=["stdio", "http"], nargs="?", default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    opt = parser.parse_args()
    try:
        bridge = Bridge.from_env()
    except (ValueError, BridgeError, OSError) as exc:
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        sys.exit(2)
    if opt.transport == "stdio":
        serve_stdio(bridge)
    else:
        pin = os.getenv('CTF_OAUTH_PIN', '')
        public_file = os.getenv('CTF_PUBLIC_URL_FILE', '')
        public_url = os.getenv('CTF_PUBLIC_URL', '')
        try:
            auth = OAuth(pin, public_file, public_url)
        except ValueError as exc:
            print(f'Invalid OAuth configuration: {exc}', file=sys.stderr)
            sys.exit(2)
        allowed_origins = set(filter(None, os.getenv('CTF_ALLOWED_ORIGINS', '').split(',')))
        token_file = os.getenv('CTF_SERVICE_TOKEN_FILE', '')
        service_token = Path(token_file).read_text().strip() if token_file else None
        if service_token is not None and not re.fullmatch(r'[A-Za-z0-9_-]{40,160}', service_token):
            print('Invalid bridge service credential file', file=sys.stderr)
            sys.exit(2)
        print(f'HTTP MCP listening at http://{opt.host}:{opt.port}/mcp', file=sys.stderr)
        BoundedHTTPServer((opt.host, opt.port), handler_factory(bridge, auth, allowed_origins, service_token)).serve_forever()


if __name__ == "__main__":
    main()
