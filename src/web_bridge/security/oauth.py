"""Tiny single-owner OAuth 2.1 PKCE gateway for a private CTF MCP bridge.

The connection is gated by an owner-only pairing PIN. Designed for one user,
not a general-purpose multi-tenant identity provider.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

SCOPE = 'ctf:access'


def safe_redirect(uri: str) -> bool:
    try:
        u = urlsplit(uri)
        return (u.scheme == 'https' and u.hostname == 'chatgpt.com'
                and (u.path.startswith('/connector/oauth/') or u.path == '/connector_platform_oauth_redirect')
                and not u.username and not u.password and not u.fragment and not u.query)
    except ValueError:
        return False


def token() -> str:
    return secrets.token_urlsafe(40)


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


class OAuth:
    def __init__(self, pin: str, url_file: str = '', public_url: str = ''):
        if len(pin) < 12:
            raise ValueError('CTF_OAUTH_PIN must contain at least 12 characters')
        self.pin = pin
        self.url_file = url_file
        self.fixed_url = public_url
        self._lock = threading.RLock()
        self.clients = {}
        self.pending = {}
        self.codes = {}
        self.access = {}
        self.refresh = {}
        self._bad_attempts = {}

    @property
    def base(self):
        # Never derive OAuth issuer URLs from caller-controlled Host or proxy headers.
        v = Path(self.url_file).read_text().strip() if self.url_file else self.fixed_url
        u = urlsplit(v)
        if u.scheme != 'https' or not u.hostname or u.path not in ('', '/') or u.query or u.fragment:
            raise ValueError('CTF public URL not configured yet')
        return v.rstrip('/')

    def _valid_resource(self, resource):
        # Different MCP client flows send either the issuer origin or the /mcp URL.
        # Both represent this same bridge, never an arbitrary resource or origin.
        return resource in (self.base, self.base + '/mcp')

    def protected(self):
        return {'resource': self.base + '/mcp', 'authorization_servers': [self.base], 'scopes_supported': [SCOPE]}

    def discovery(self):
        b = self.base
        return {'issuer': b, 'authorization_endpoint': b + '/authorize', 'token_endpoint': b + '/token',
                'registration_endpoint': b + '/register', 'response_types_supported': ['code'],
                'grant_types_supported': ['authorization_code', 'refresh_token'],
                'code_challenge_methods_supported': ['S256'],
                'token_endpoint_auth_methods_supported': ['none'], 'scopes_supported': [SCOPE],
                'authorization_response_iss_parameter_supported': True}

    def register(self, data):
        uris = data.get('redirect_uris') or []
        if not isinstance(uris, list) or not uris or len(uris) > 8 or not all(isinstance(x, str) and safe_redirect(x) for x in uris):
            raise ValueError('Only ChatGPT official OAuth callback URIs allowed')
        if data.get('token_endpoint_auth_method', 'none') != 'none':
            raise ValueError('Only public OAuth clients supported')
        client_id = 'ctf-' + token()
        with self._lock:
            if len(self.clients) >= 24:
                raise ValueError('Registration capacity exceeded. Restart bridge to clear registrations.')
            self.clients[client_id] = set(uris)
        return {'client_id': client_id, 'client_id_issued_at': int(time.time()),
                'redirect_uris': uris, 'token_endpoint_auth_method': 'none',
                'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']}

    def authorize(self, data):
        cid, redirect = data.get('client_id', ''), data.get('redirect_uri', '')
        with self._lock:
            if redirect not in self.clients.get(cid, set()) or data.get('response_type') != 'code':
                raise ValueError('Unregistered OAuth client or redirect URI')
            if data.get('code_challenge_method') != 'S256' or len(data.get('code_challenge', '')) < 40:
                raise ValueError('PKCE S256 required')
            if not self._valid_resource(data.get('resource', self.base + '/mcp')):
                raise ValueError('Wrong resource')
            scopes = data.get('scope', SCOPE).split()
            if SCOPE not in scopes or any(s != SCOPE for s in scopes):
                raise ValueError('Unsupported scope')
            ticket = token()
            self.pending[ticket] = {'request': dict(data), 'expires': time.time()+300}
        return ticket

    def login_html(self, ticket):
        return ("<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>CTF Bridge pairing</title></head><body style='font:16px system-ui;max-width:420px;margin:12vh auto;padding:24px'>"
                "<h2>CTF Instance Bridge</h2><p>Only approve if you initiated this ChatGPT connection. "
                "This grants access to your authorized CTF target.</p><form method='post' action='/authorize'>"
                f"<input type='hidden' name='ticket' value='{html.escape(ticket, quote=True)}'>"
                "<label>Pairing PIN from your terminal:<br><input required type='password' name='pin' "
                "autocomplete='off' style='width:100%;padding:10px;margin:10px 0'></label>"
                "<button style='padding:10px 20px'>Authorize connection</button></form></body></html>")

    def approve(self, ticket, pin, remote_id='local'):
        with self._lock:
            now = time.time()
            attempts = self._bad_attempts.get(remote_id, [])
            attempts = [t for t in attempts if now-t < 300]
            if len(attempts) >= 8:
                raise ValueError('Too many attempts; wait five minutes')
            if not hmac.compare_digest(pin, self.pin):
                attempts.append(now)
                self._bad_attempts[remote_id] = attempts
                raise ValueError('Invalid pairing PIN')
            v = self.pending.pop(ticket, None)
            if not v or v['expires'] < now:
                raise ValueError('Authorization attempt expired')
            request = v['request']
            code = token()
            self.codes[code] = {'request': request, 'expires': now+120}
            query = {'code': code, 'iss': self.base}
            if 'state' in request:
                query['state'] = request['state']
            return request['redirect_uri']+'?'+urlencode(query)

    def exchange(self, data):
        now = time.time()
        grant = data.get('grant_type')
        cid = data.get('client_id', '')
        with self._lock:
            if grant == 'authorization_code':
                code = data.get('code', '')
                saved = self.codes.pop(code, None)
                if not saved or saved['expires'] < now:
                    raise ValueError('Invalid/expired authorization code')
                req = saved['request']
                if cid != req['client_id'] or data.get('redirect_uri') != req['redirect_uri']:
                    raise ValueError('Client or redirect mismatch')
                verifier = data.get('code_verifier', '')
                if not isinstance(verifier, str) or not 43 <= len(verifier) <= 128 or not hmac.compare_digest(challenge(verifier), req['code_challenge']):
                    raise ValueError('PKCE verification failed')
            elif grant == 'refresh_token':
                old = self.refresh.pop(data.get('refresh_token', ''), None)
                if not old or old['client_id'] != cid or old['expires'] < now:
                    raise ValueError('Invalid/expired refresh token')
            else:
                raise ValueError('Unsupported grant')
            if cid not in self.clients:
                raise ValueError('Unknown client')
            if not self._valid_resource(data.get('resource', self.base+'/mcp')):
                raise ValueError('Wrong OAuth resource')
            access, refresh = token(), token()
            self.access[access] = {'client_id': cid, 'expires': now+3600, 'aud': self.base+'/mcp', 'scope': SCOPE}
            self.refresh[refresh] = {'client_id': cid, 'expires': now+86400}
        return {'access_token': access, 'token_type': 'Bearer', 'expires_in': 3600,
                'refresh_token': refresh, 'scope': SCOPE}

    def check(self, raw):
        if not raw.startswith('Bearer '):
            return False
        key = raw[7:]
        with self._lock:
            v = self.access.get(key)
            return bool(v and v['expires'] > time.time() and v['aud'] == self.base+'/mcp' and v['scope'] == SCOPE)
