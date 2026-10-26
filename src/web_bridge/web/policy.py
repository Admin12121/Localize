"""Shared HTTP/browser limits, errors and redirect policy."""
from urllib.request import HTTPRedirectHandler

MAX_BODY = 1_000_000
MAX_TEXT = 80_000
BLOCKED_HEADERS = {"host", "connection", "transfer-encoding", "content-length", "proxy-authorization", "proxy-connection", "upgrade", "accept-encoding"}


class BridgeError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


