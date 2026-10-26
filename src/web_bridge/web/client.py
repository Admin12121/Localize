#!/usr/bin/env python3
"""CTF Instance Bridge: allowlisted MCP HTTP/browser client, stdlib MCP transport."""

from __future__ import annotations

import base64
import html.parser
import http.cookiejar
import json
import os
import re
import socket
import threading
import time
import hashlib
import ipaddress
import secrets
from collections import deque
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit, urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, ProxyHandler
from web_bridge.web.network import PinnedHTTPHandler, PinnedHTTPSHandler

VERSION = "2.0.0"

from web_bridge.web.policy import (
    MAX_BODY,
    MAX_TEXT,
    BLOCKED_HEADERS,
    BridgeError,
    NoRedirect,
)


class HtmlSummary(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.forms, self.scripts, self.comments, self.current_form = (
            [],
            [],
            [],
            [],
            None,
        )
        self.metadata, self.title, self._tag = [], "", ""

    def handle_starttag(self, tag, attrs):
        self._tag = tag
        attrs = dict(attrs)
        if tag == "meta" and len(self.metadata) < 100:
            self.metadata.append(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append({"href": attrs["href"], "label": ""})
        if tag == "script":
            self.scripts.append({"src": attrs.get("src", "inline")})
        if tag == "form":
            self.current_form = {
                "action": attrs.get("action", ""),
                "method": attrs.get("method", "get"),
                "inputs": [],
            }
            self.forms.append(self.current_form)
        if (
            tag in ("input", "textarea", "select", "button")
            and self.current_form is not None
        ):
            self.current_form["inputs"].append(
                {k: attrs.get(k, "") for k in ("name", "type", "value", "id")}
            )

    def handle_endtag(self, tag):
        self._tag = ""
        if tag == "form":
            self.current_form = None

    def handle_data(self, data):
        if self._tag == "title":
            self.title += data[:500]
        if self._tag == "a" and self.links:
            self.links[-1]["label"] += data[:200]
        if (
            self._tag == "script"
            and self.scripts
            and self.scripts[-1]["src"] == "inline"
        ):
            self.scripts[-1]["text"] = self.scripts[-1].get("text", "") + data[:8000]

    def handle_comment(self, data):
        if len(self.comments) < 30:
            self.comments.append(data[:500])


from web_bridge.web.browser import BrowserActions


class Bridge(BrowserActions):
    def __init__(
        self, targets: dict[str, str], *, allow_private=False, min_interval=0.1
    ):
        if not isinstance(targets, dict):
            raise BridgeError("CTF_TARGETS must be a JSON object of name: origin")
        self.targets: dict[str, str] = {}
        if len(targets) > 20:
            raise BridgeError("At most 20 approved targets are supported")
        for name, url in targets.items():
            if not isinstance(name, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,40}", name
            ):
                raise BridgeError(
                    "Target name must be 1-40 alphanumeric characters, _ or -"
                )
            if (
                not isinstance(url, str)
                or len(url) > 300
                or any(c.isspace() or ord(c) < 32 for c in url)
                or "\\" in url
            ):
                raise BridgeError("Invalid approved origin")
            parsed = urlsplit(url)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
            ):
                raise BridgeError(
                    f"Invalid origin for {name}; use only scheme://host[:port]"
                )
            try:
                _ = parsed.port
            except ValueError as exc:
                raise BridgeError(f"Bad port for {name}") from exc
            self.targets[name] = urlunsplit(
                (parsed.scheme, parsed.netloc.lower(), "", "", "")
            )
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
        return cls(
            json.loads(raw or "{}"),
            allow_private=os.getenv("CTF_ALLOW_PRIVATE", "0") == "1",
            min_interval=float(os.getenv("CTF_MIN_REQUEST_INTERVAL", "0.1")),
        )

    def _origin(self, target):
        if getattr(self, "cancelled", lambda: False)():
            raise BridgeError("CTF access was revoked locally.")
        if target not in self.targets:
            raise BridgeError(
                "Unknown target; list_targets first. Targets can only be configured by the server owner."
            )
        origin = self.targets[target]
        hostname = urlsplit(origin).hostname
        try:
            addresses = tuple(
                sorted(
                    {
                        a[4][0]
                        for a in socket.getaddrinfo(
                            hostname,
                            urlsplit(origin).port
                            or (443 if origin.startswith("https:") else 80),
                            type=socket.SOCK_STREAM,
                        )
                    }
                )
            )
        except OSError as exc:
            raise BridgeError("Target DNS lookup failed") from exc
        if (
            not addresses
            or not self.allow_private
            and any(not ipaddress.ip_address(a).is_global for a in addresses)
        ):
            raise BridgeError(
                "Non-public destination rejected. Explicitly opt into a private lab on Linux."
            )
        with self._lock:
            pinned = self._pins.setdefault(target, addresses)
            if not set(addresses).issubset(pinned):
                raise BridgeError(
                    "Target DNS changed. Review the approved origin and restart the bridge to repin."
                )
        return origin

    def _url(self, target, path):
        origin = self._origin(target)
        if (
            not isinstance(path, str)
            or len(path) > 8192
            or not path.startswith("/")
            or path.startswith("//")
            or "\\" in path
            or "#" in path
            or any(ord(c) < 32 or ord(c) == 127 for c in path)
        ):
            raise BridgeError(
                "Path must be a same-origin absolute path starting with one slash"
            )
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
                self._opener[target] = build_opener(
                    ProxyHandler({}),
                    HTTPCookieProcessor(jar),
                    NoRedirect(),
                    PinnedHTTPHandler(self._pins[target]),
                    PinnedHTTPSHandler(self._pins[target]),
                )
            return self._opener[target]

    def list_targets(self):
        return {
            "targets": [{"name": k, "origin": v} for k, v in self.targets.items()],
            "count": len(self.targets),
        }

    def reset_session(self, target):
        self._origin(target)
        with self._lock:
            self._opener.pop(target, None)
            self._cookies.pop(target, None)
            self._last_request.pop(target, None)
        if self._browser_process is not None:
            self._browser_process.call(target, "reset", "/", "", "", "")
        return {"target": target, "reset": True}

    def _redact(self, text):
        for jar in self._cookies.values():
            self._secret_values.update(c.value for c in jar if c.value)
        for secret in sorted(self._secret_values, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED]")
        return text

    def _redact_tree(self, obj):
        if isinstance(obj, str):
            return self._redact(obj)
        if isinstance(obj, dict):
            return {k: self._redact_tree(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._redact_tree(v) for v in obj]
        return obj

    def request_history(self, target, limit=20):
        self._origin(target)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise BridgeError("History limit must be 1-100")
        return {
            "target": target,
            "entries": list(self._history[target])[-limit:],
            "retained": len(self._history[target]),
        }

    def session_cookies(self, target):
        self._origin(target)
        self._session(target)
        with self._lock:
            return {
                "cookies": [
                    {
                        "name": c.name,
                        "domain": c.domain,
                        "path": c.path,
                        "secure": c.secure,
                        "expires": c.expires,
                        "http_only": c.has_nonstandard_attr("HttpOnly"),
                    }
                    for c in self._cookies[target]
                ]
            }

    def http_request(
        self,
        target,
        method="GET",
        path="/",
        headers=None,
        body=None,
        body_base64=None,
        timeout_seconds=12,
        params=None,
        json_body=None,
        form=None,
        files=None,
    ):
        if params is not None:
            if not isinstance(params, dict) or len(params) > 100:
                raise BridgeError(
                    "Parameters must be an object with at most 100 fields"
                )
            path += ("&" if "?" in path else "?") + urlencode(params, doseq=True)
        url = self._url(target, path)
        if not isinstance(method, str):
            raise BridgeError("HTTP method must be text")
        method = method.upper()
        if method not in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            raise BridgeError("Unsupported HTTP method")
        if (
            sum(v is not None for v in (body, body_base64, json_body, form)) > 1
            or files is not None
            and any(v is not None for v in (body, body_base64, json_body))
        ):
            raise BridgeError(
                "Choose one body encoding; multipart files can be combined with form fields"
            )
        if not isinstance(headers or {}, dict) or len(headers or {}) > 50:
            raise BridgeError("Headers must be a JSON object with at most 50 keys")
        hdr = {"User-Agent": "CTF-Instance-Bridge/1.0", "Accept-Encoding": "identity"}
        for k, v in (headers or {}).items():
            if (
                not isinstance(k, str)
                or not isinstance(v, str)
                or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,100}", k)
                or len(v) > 8192
                or k.lower() in BLOCKED_HEADERS
                or "\r" in k + v
                or "\n" in k + v
                or "\x00" in v
            ):
                raise BridgeError(f"Unsafe header: {k}")
            hdr[k] = v
            if k.lower() in ("authorization", "cookie", "x-api-key") and v:
                self._secret_values.add(v)
                if k.lower() == "authorization" and " " in v:
                    self._secret_values.add(v.split(" ", 1)[1])
        try:
            if files is not None:
                if (
                    not isinstance(files, list)
                    or not 1 <= len(files) <= 5
                    or form is not None
                    and not isinstance(form, dict)
                ):
                    raise BridgeError(
                        "Multipart supports up to 5 files and an optional form object"
                    )
                boundary = "ctf-" + secrets.token_hex(16)
                chunks = []
                for name, value in (form or {}).items():
                    if not isinstance(name, str) or not re.fullmatch(
                        r"[A-Za-z0-9_.-]{1,100}", name
                    ):
                        raise BridgeError("Unsafe form field name")
                    chunks.append(
                        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
                    )
                for file in files:
                    if not isinstance(file, dict) or set(file) - {
                        "field",
                        "filename",
                        "content_type",
                        "data_base64",
                    }:
                        raise BridgeError("Invalid multipart file")
                    field, filename = file.get("field", "file"), file.get(
                        "filename", "upload.bin"
                    )
                    ct = file.get("content_type", "application/octet-stream")
                    if (
                        not isinstance(field, str)
                        or not isinstance(filename, str)
                        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", field)
                        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", filename)
                        or not isinstance(ct, str)
                        or not re.fullmatch(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+", ct)
                    ):
                        raise BridgeError(
                            "Unsafe upload filename, field, or content type"
                        )
                    blob = base64.b64decode(file.get("data_base64", ""), validate=True)
                    chunks.append(
                        f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\nContent-Type: {ct}\r\n\r\n'.encode()
                        + blob
                        + b"\r\n"
                    )
                payload = b"".join(chunks) + f"--{boundary}--\r\n".encode()
                hdr["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            elif json_body is not None:
                payload = json.dumps(json_body, ensure_ascii=False).encode()
                hdr.setdefault("Content-Type", "application/json")
            elif form is not None:
                if not isinstance(form, dict) or len(form) > 100:
                    raise BridgeError("Form must be an object with at most 100 fields")
                payload = urlencode(form, doseq=True).encode()
                hdr.setdefault("Content-Type", "application/x-www-form-urlencoded")
            else:
                payload = (
                    base64.b64decode(body_base64, validate=True)
                    if body_base64 is not None
                    else (body.encode("utf-8") if body is not None else None)
                )
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
                response = (
                    err  # 3xx (redirects disabled) and 4xx/5xx are useful evidence
                )
            except (URLError, TimeoutError, OSError) as err:
                return {"error": str(err), "url": url}
            try:
                chunks, length = [], 0
                while length <= MAX_BODY:
                    remaining = timeout_seconds - (time.monotonic() - start)
                    if remaining <= 0:
                        raise TimeoutError("Response deadline exceeded")
                    try:
                        response.fp.raw._sock.settimeout(remaining)
                    except AttributeError:
                        pass
                    chunk = response.read1(min(65536, MAX_BODY + 1 - length))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    length += len(chunk)
                data = b"".join(chunks)
                truncated = len(data) > MAX_BODY
                if truncated:
                    data = data[:MAX_BODY]
                hs = dict(response.headers.items())
                hs = {
                    k: (
                        "[REDACTED: stored in target session]"
                        if k.lower() == "set-cookie"
                        else v
                    )
                    for k, v in hs.items()
                }
                ct = response.headers.get("Content-Type", "")
                charset = response.headers.get_content_charset() or "utf-8"
                textual = not ct or any(
                    x in ct.lower()
                    for x in ("text/", "json", "xml", "javascript", "html")
                )
                try:
                    decoded = (
                        data[:MAX_TEXT].decode(charset, errors="replace")
                        if textual
                        else ""
                    )
                except LookupError:
                    decoded = (
                        data[:MAX_TEXT].decode("utf-8", errors="replace")
                        if textual
                        else ""
                    )
                decoded = self._redact(decoded)
                evidence_id = secrets.token_hex(12)
                result = {
                    "url": self._redact(url),
                    "method": method,
                    "status": response.status,
                    "elapsed_ms": round((time.monotonic() - start) * 1000),
                    "headers": {k: self._redact(v) for k, v in hs.items()},
                    "body_text": decoded,
                    "body_base64": (
                        base64.b64encode(data).decode("ascii")
                        if not textual
                        and not any(s.encode() in data for s in self._secret_values)
                        else None
                    ),
                    "body_bytes": len(data),
                    "truncated": truncated or textual and len(data) > MAX_TEXT,
                    "request_id": evidence_id,
                    "body_sha256": hashlib.sha256(data).hexdigest(),
                }
                self._history[target].append(
                    {
                        "request_id": evidence_id,
                        "timestamp": int(time.time()),
                        "method": method,
                        "url": self._redact(url),
                        "status": response.status,
                        "request_bytes": len(payload or b""),
                        "response_bytes": len(data),
                        "body_sha256": result["body_sha256"],
                        "elapsed_ms": result["elapsed_ms"],
                        "truncated": result["truncated"],
                    }
                )
                return result
            finally:
                response.close()

    def http_batch(self, target, requests):
        if not isinstance(requests, list) or not 1 <= len(requests) <= 10:
            raise BridgeError("Provide between 1 and 10 requests")
        out = []
        deadline = time.monotonic() + 45
        for i, r in enumerate(requests):
            if getattr(self, "cancelled", lambda: False)():
                raise BridgeError("CTF access was revoked locally.")
            if not isinstance(r, dict):
                raise BridgeError("Each request must be an object")
            if "target" in r:
                raise BridgeError("Batch items cannot change target")
            if time.monotonic() >= deadline:
                raise BridgeError("Batch time budget exceeded")
            r = dict(r)
            r["timeout_seconds"] = min(
                float(r.get("timeout_seconds", 12)), deadline - time.monotonic()
            )
            item = self.http_request(target, **r)
            out.append({"index": i, **item})
            if len(json.dumps(out)) > 1_500_000:
                raise BridgeError("Batch output size exceeded; use individual requests")
        return {"results": out}

    def inspect_html(self, target, path="/"):
        result = self.http_request(target, path=path)
        if result.get("error"):
            return result
        parser = HtmlSummary()
        parser.feed(result["body_text"])
        return {
            "status": result["status"],
            "url": result["url"],
            "links": parser.links[:150],
            "forms": parser.forms[:30],
            "scripts": parser.scripts[:100],
            "comments": parser.comments,
            "title": parser.title,
            "metadata": parser.metadata,
            "request_id": result["request_id"],
        }
