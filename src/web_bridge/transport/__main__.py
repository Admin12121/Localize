"""Legacy web-only MCP transport entry, independent of local project grants."""
import argparse
import os
from pathlib import Path
import re
import sys
from web_bridge.web.client import Bridge, BridgeError
from web_bridge.security.oauth import OAuth
from web_bridge.transport.rpc import serve_stdio
from web_bridge.transport.http import BoundedHTTPServer, handler_factory

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
