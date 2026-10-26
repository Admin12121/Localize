#!/usr/bin/env bash
# CTF Web Bridge: one-command authenticated network bridge + Cloudflare Quick Tunnel.
# Use only with challenge instances you are authorized to test.
set -Eeuo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage:
  ./start-cloudflare-tunnel.sh 'https://challenge.example:8443'
  ./start-cloudflare-tunnel.sh  # prompts for an origin

Environment overrides:
  CTF_TARGETS              JSON map of names to authorized origins (optional)
  CTF_ALLOW_PRIVATE=1      Permit private/loopback target addresses in your lab
  CTF_BRIDGE_PORT=8765     Local MCP HTTP port
  CTF_CONFIG              Owner-managed targets JSON file
  CTF_OAUTH_PIN            Legacy optional pairing PIN (otherwise auto-generated)

Output: an HTTPS https://*.trycloudflare.com/mcp endpoint. This is an
EPHEMERAL Quick Tunnel; keep the terminal running to keep it accessible.
Connect normal Chat through the private Site-generated plugin. Paste the
connection key ONLY into the Site settings password field. Never into chat.
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac
if (( $# > 1 )); then usage >&2; exit 2; fi

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
BRIDGE="$ROOT/src/web_bridge/transport/rpc.py"
if [[ ! -f "$BRIDGE" || ! -f "$ROOT/src/web_bridge/security/oauth.py" ]]; then
  echo 'Old/incomplete bridge files. Extract the entire v1.2 ZIP to replace your existing directory.' >&2
  exit 1
fi
if ! grep -q '^VERSION = "2.0.0"' "$BRIDGE"; then
  echo 'Old bridge version. Extract the complete Sites bridge update.' >&2; exit 1
fi
command -v python3 >/dev/null || { echo 'python3 (3.10+) is required.' >&2; exit 1; }

if [[ -n "${CTF_CONFIG:-}" ]]; then
  [[ -f "$CTF_CONFIG" ]] || { echo 'Target configuration file missing.' >&2; exit 2; }
elif [[ -z "${CTF_TARGETS:-}" ]]; then
  TARGET="${1:-}"
  if [[ -z "$TARGET" ]]; then
    if [[ -t 0 ]]; then
      read -r -p 'Authorized CTF target origin (http[s]://host[:port]): ' TARGET
    else
      echo 'Provide the target URL as the first argument.' >&2; exit 2
    fi
  fi
  export CTF_TARGET="$TARGET"
  CTF_TARGETS="$(python3 - <<'PY'
import json, os, sys
from urllib.parse import urlsplit
u = os.environ['CTF_TARGET'].strip()
try:
    p = urlsplit(u)
    _ = p.port
except ValueError:
    sys.exit('Invalid port in target URL')
if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.path not in ('', '/') or p.query or p.fragment:
    sys.exit('Target must be only an origin, e.g. https://example.com:8443 (no path/query)')
print(json.dumps({'lab': u.rstrip('/')}))
PY
)" || exit 2
  export CTF_TARGETS
else
  python3 - <<'PY'
import json, os
x=json.loads(os.environ['CTF_TARGETS'])
if not isinstance(x, dict) or not x:
    raise SystemExit('CTF_TARGETS must be a nonempty JSON object')
PY
fi

PORT="${CTF_BRIDGE_PORT:-8765}"
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1024 || PORT > 65535 )); then
  echo 'CTF_BRIDGE_PORT must be an unprivileged TCP port, 1024-65535.' >&2; exit 2
fi

RUNTIME="$ROOT/.runtime"
mkdir -p "$RUNTIME/bin"
chmod 700 "$RUNTIME" "$RUNTIME/bin"
PIN_FILE="$RUNTIME/oauth-pin"
if [[ -z "${CTF_OAUTH_PIN:-}" ]]; then
  if [[ -s "$PIN_FILE" ]]; then
    CTF_OAUTH_PIN="$(<"$PIN_FILE")"
  else
    CTF_OAUTH_PIN="$(python3 - <<'PY_PIN'
import secrets
print(secrets.token_urlsafe(24))
PY_PIN
)"
  fi
fi
if (( ${#CTF_OAUTH_PIN} < 12 )); then
  echo 'CTF_OAUTH_PIN must be at least 12 characters.' >&2; exit 2
fi
printf '%s\n' "$CTF_OAUTH_PIN" > "$PIN_FILE"
chmod 600 "$PIN_FILE"
export CTF_OAUTH_PIN
export CTF_SERVICE_TOKEN_FILE="$RUNTIME/site-connection-key"
if [[ ! -s "$CTF_SERVICE_TOKEN_FILE" ]]; then
  python3 - <<'PY_KEY' > "$CTF_SERVICE_TOKEN_FILE"
import secrets
print(secrets.token_urlsafe(48))
PY_KEY
fi
chmod 600 "$CTF_SERVICE_TOKEN_FILE"
export CTF_PUBLIC_URL_FILE="$RUNTIME/public-url"
# Clear stale issuer config before launching the new tunnel.
: > "$CTF_PUBLIC_URL_FILE"
chmod 600 "$CTF_PUBLIC_URL_FILE"

# Install a user-local cloudflared binary on Linux when it is missing.
CF="$(command -v cloudflared || true)"
if [[ -z "$CF" && -x "$RUNTIME/bin/cloudflared" ]]; then CF="$RUNTIME/bin/cloudflared"; fi
if [[ -z "$CF" ]]; then
  if [[ "$(uname -s)" != Linux ]]; then
    echo 'cloudflared not found. Install it (macOS: brew install cloudflared), then rerun.' >&2
    exit 1
  fi
  command -v curl >/dev/null || { echo 'curl is required to download cloudflared.' >&2; exit 1; }
  case "$(uname -m)" in
    x86_64|amd64) ARCH=amd64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    armv7l) ARCH=arm ;;
    *) echo 'Unsupported architecture: install cloudflared manually.' >&2; exit 1 ;;
  esac
  echo 'cloudflared not found; downloading official binary from Cloudflare GitHub releases...'
  TEMP="$RUNTIME/bin/cloudflared.download.$$"
  trap 'rm -f -- "$TEMP"' EXIT
  curl --fail --location --show-error --silent --retry 2 --connect-timeout 10 --max-time 180 \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$ARCH" -o "$TEMP"
  chmod 700 "$TEMP"
  mv -f -- "$TEMP" "$RUNTIME/bin/cloudflared"
  trap - EXIT
  CF="$RUNTIME/bin/cloudflared"
fi

BRIDGE_LOG="$RUNTIME/bridge.log"
TUNNEL_LOG="$RUNTIME/cloudflared.log"
: > "$BRIDGE_LOG"
: > "$TUNNEL_LOG"
BRIDGE_PID=''
TUNNEL_PID=''
cleanup() {
  trap - EXIT INT TERM
  echo
  echo 'Stopping tunnel and MCP bridge...'
  [[ -n "$TUNNEL_PID" ]] && kill "$TUNNEL_PID" 2>/dev/null || true
  [[ -n "$BRIDGE_PID" ]] && kill "$BRIDGE_PID" 2>/dev/null || true
  [[ -n "$TUNNEL_PID" ]] && wait "$TUNNEL_PID" 2>/dev/null || true
  [[ -n "$BRIDGE_PID" ]] && wait "$BRIDGE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

export CTF_ALLOWED_ORIGINS="${CTF_ALLOWED_ORIGINS:-https://chatgpt.com,https://chat.openai.com}"
echo 'Starting authenticated MCP server on 127.0.0.1...'
python3 -u -m web_bridge.transport http --host 127.0.0.1 --port "$PORT" > "$BRIDGE_LOG" 2>&1 &
BRIDGE_PID=$!
READY=0
for _ in {1..30}; do
  if ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
    echo 'MCP server stopped unexpectedly:' >&2; tail -n 25 "$BRIDGE_LOG" >&2; exit 1
  fi
  if python3 - "$PORT" <<'PY' >/dev/null 2>&1
import sys, urllib.request
with urllib.request.urlopen('http://127.0.0.1:%s/health' % sys.argv[1], timeout=1) as r:
    assert r.status == 200
PY
  then READY=1; break; fi
  sleep 0.3
done
if (( READY != 1 )); then
  echo 'MCP server did not become ready:' >&2; tail -n 25 "$BRIDGE_LOG" >&2; exit 1
fi

echo 'Starting Cloudflare Quick Tunnel (no account required)...'
"$CF" tunnel --url "http://127.0.0.1:$PORT" > "$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!
PUBLIC_URL=''
for _ in {1..75}; do
  if [[ -f "$TUNNEL_LOG" ]]; then
    PUBLIC_URL="$(grep -Eom1 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" || true)"
  fi
  [[ -n "$PUBLIC_URL" ]] && break
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo 'cloudflared failed:' >&2; tail -n 30 "$TUNNEL_LOG" >&2; exit 1
  fi
  sleep 1
done
if [[ -z "$PUBLIC_URL" ]]; then
  echo 'Timed out waiting for a trycloudflare.com URL. Log:' >&2
  tail -n 30 "$TUNNEL_LOG" >&2; exit 1
fi

printf '%s\n' "$PUBLIC_URL" > "$CTF_PUBLIC_URL_FILE"

printf '\n%s\n' '============================================================'
printf ' MCP ENDPOINT: %s/mcp\n' "$PUBLIC_URL"
printf ' HEALTH CHECK: %s/health\n' "$PUBLIC_URL"
printf ' SITE CONNECTION KEY: %s\n' "$(<"$CTF_SERVICE_TOKEN_FILE")"
printf '%s\n' '============================================================'
printf '%s\n' 'Save the endpoint and connection key in your private CTF Web Bridge Site.'
printf '%s\n' 'Never paste the key or legacy pairing PIN into chat or any URL.'
printf '%s\n' 'Keep this terminal open. Press Ctrl+C to stop.'
printf 'Logs: %s and %s\n\n' "$BRIDGE_LOG" "$TUNNEL_LOG"
while kill -0 "$BRIDGE_PID" 2>/dev/null && kill -0 "$TUNNEL_PID" 2>/dev/null; do
  sleep 2
done
echo 'A subprocess exited; check the logs above.' >&2
exit 1
