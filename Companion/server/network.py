"""Pinned direct connections: no environment proxies or second hostname lookup."""
import http.client
import socket
import ssl
from urllib.request import HTTPHandler, HTTPSHandler


def connect(addresses, port, timeout):
    last_error = None
    for address in addresses:
        family = socket.AF_INET6 if ':' in address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((address, port))
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise last_error or OSError('No pinned destination available')


class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, *, addresses, **kwargs):
        super().__init__(host, **kwargs)
        self.addresses = addresses

    def connect(self):
        self.sock = connect(self.addresses, self.port, self.timeout)


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, *, addresses, **kwargs):
        super().__init__(host, **kwargs)
        self.addresses = addresses

    def connect(self):
        raw = connect(self.addresses, self.port, self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


class PinnedHTTPHandler(HTTPHandler):
    def __init__(self, addresses):
        super().__init__()
        self.addresses = addresses

    def http_open(self, req):
        return self.do_open(lambda host, **kwargs: PinnedHTTP(host, addresses=self.addresses, **kwargs), req)


class PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, addresses):
        super().__init__(context=ssl.create_default_context())
        self.addresses = addresses

    def https_open(self, req):
        return self.do_open(lambda host, **kwargs: PinnedHTTPS(host, addresses=self.addresses, **kwargs), req, context=self._context)
