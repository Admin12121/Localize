"""Optional browser actions; imported without launching a browser."""

import json
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, Request
from collections import deque
from web_bridge.web.policy import (
    BridgeError,
    NoRedirect,
    MAX_BODY,
    MAX_TEXT,
    BLOCKED_HEADERS,
)
from web_bridge.web.network import PinnedHTTPHandler, PinnedHTTPSHandler


class BrowserActions:
    def browser_action(
        self, target, action="visit", path="/", selector="", value="", script=""
    ):
        """Optional isolated Chromium worker. All Playwright calls run on the same thread."""
        self._origin(target)
        if action not in (
            "visit",
            "snapshot",
            "click",
            "fill",
            "press",
            "evaluate",
            "diagnostics",
        ):
            raise BridgeError("Unknown browser action")
        if action in ("click", "fill", "press") and not selector:
            raise BridgeError("Browser selector is required")
        from web_bridge.web.browser_process import BrowserProcess

        with self._lock:
            if self._browser_process is None:
                self._browser_process = BrowserProcess(
                    self.targets,
                    self.allow_private,
                    self.min_interval,
                    dict(self._pins),
                )
        return self._browser_process.call(target, action, path, selector, value, script)

    def _browser_route(self, route, target):
        """Mediate Chromium HTTP(S) through pinned direct connections; Chromium cannot choose DNS."""
        request = route.request
        events = self._browser_events[target]
        try:
            origin = self._origin(target)
            parsed = urlsplit(request.url)
            if (
                parsed.scheme not in ("http", "https")
                or f"{parsed.scheme}://{parsed.netloc}" != origin
                or parsed.username
                or parsed.password
            ):
                raise BridgeError("Browser off-origin request blocked")
            headers = {
                k: v
                for k, v in request.headers.items()
                if k.lower() not in BLOCKED_HEADERS
            }
            headers["Accept-Encoding"] = "identity"
            payload = request.post_data_buffer
            if payload and len(payload) > MAX_BODY:
                raise BridgeError("Browser upload exceeds 1 MB")
            opener = build_opener(
                ProxyHandler({}),
                NoRedirect(),
                PinnedHTTPHandler(self._pins[target]),
                PinnedHTTPSHandler(self._pins[target]),
            )
            try:
                response = opener.open(
                    Request(
                        request.url,
                        data=payload,
                        headers=headers,
                        method=request.method,
                    ),
                    timeout=12,
                )
            except HTTPError as exc:
                response = exc
            try:
                data = response.read(MAX_BODY + 1)
                if len(data) > MAX_BODY:
                    raise BridgeError("Browser response exceeds 1 MB")
                hs = {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower()
                    not in ("content-length", "transfer-encoding", "connection")
                }
                route.fulfill(status=response.status, headers=hs, body=data)
                events.append(
                    {
                        "type": "network",
                        "method": request.method,
                        "url": request.url.split("?")[0],
                        "status": response.status,
                        "bytes": len(data),
                    }
                )
            finally:
                response.close()
        except Exception:
            events.append(
                {
                    "type": "blocked_or_failed",
                    "method": request.method,
                    "url": request.url.split("?")[0],
                }
            )
            route.abort()

    def _browser_loop(self):
        """A single thread owns Playwright to avoid sync API cross-thread failures."""
        pw, browser = None, None
        while True:
            future, target, action, path, selector, value, script = (
                self._browser_queue.get()
            )
            try:
                if action == "reset":
                    page = self._browser_pages.pop(target, None)
                    if page:
                        page.context.close()
                    self._browser_events.pop(target, None)
                    future.set_result({"reset": True})
                    continue
                if browser is None:
                    try:
                        from playwright.sync_api import sync_playwright
                    except ImportError as exc:
                        raise BridgeError(
                            "Install optional browser: pip install playwright && playwright install chromium"
                        ) from exc
                    pw = sync_playwright().start()
                    browser = pw.chromium.launch(
                        headless=True,
                        chromium_sandbox=True,
                        args=[
                            "--disable-quic",
                            "--host-resolver-rules=MAP * ~NOTFOUND",
                            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                        ],
                    )
                if target not in self._browser_pages:
                    self._origin(target)
                    ctx = browser.new_context(
                        accept_downloads=False, service_workers="block"
                    )
                    ctx.add_init_script(
                        "for (const key of ['RTCPeerConnection','webkitRTCPeerConnection','WebTransport','Worker','SharedWorker']) Object.defineProperty(globalThis,key,{value:undefined,writable:false,configurable:false});"
                    )
                    self._browser_events[target] = deque(maxlen=100)
                    ctx.route(
                        "**/*",
                        lambda route, request, target=target: self._browser_route(
                            route, target
                        ),
                    )
                    if not hasattr(ctx, "route_web_socket"):
                        ctx.close()
                        raise BridgeError(
                            "Playwright 1.48+ required to block unsupported WebSocket traffic"
                        )
                    ctx.route_web_socket("**/*", lambda ws: ws.close())
                    self._browser_pages[target] = ctx.new_page()
                    self._browser_pages[target].on(
                        "console",
                        lambda msg, target=target: self._browser_events[target].append(
                            {
                                "type": "console",
                                "level": msg.type,
                                "text": msg.text[:2000],
                            }
                        ),
                    )
                    self._browser_pages[target].on(
                        "pageerror",
                        lambda err, target=target: self._browser_events[target].append(
                            {"type": "pageerror", "text": str(err)[:2000]}
                        ),
                    )
                page = self._browser_pages[target]
                page.set_default_timeout(12000)
                if action == "visit":
                    page.goto(
                        self._url(target, path),
                        wait_until="domcontentloaded",
                        timeout=20000,
                    )
                elif action == "click":
                    page.locator(selector).first.click()
                elif action == "fill":
                    page.locator(selector).first.fill(value)
                elif action == "press":
                    page.locator(selector).first.press(value)
                elif action == "evaluate":
                    output = page.evaluate(script)
                    self._secret_values.update(
                        c["value"] for c in page.context.cookies() if c.get("value")
                    )
                    future.set_result(
                        {
                            "url": page.url,
                            "value": self._redact(
                                json.dumps(output, ensure_ascii=False)
                            )[:MAX_TEXT],
                        }
                    )
                    continue
                self._secret_values.update(
                    c["value"] for c in page.context.cookies() if c.get("value")
                )
                result = (
                    {"url": page.url, "events": list(self._browser_events[target])}
                    if action == "diagnostics"
                    else {
                        "url": page.url,
                        "title": page.title(),
                        "html": page.content()[:MAX_TEXT],
                    }
                )
                future.set_result(self._redact_tree(result))
            except Exception as exc:
                future.set_exception(
                    BridgeError(f"Browser failed: {self._redact(str(exc))}")
                )
