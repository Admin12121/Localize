#!/usr/bin/env sh
set -eu
BRIDGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$BRIDGE_ROOT/run.py" "$@"
