#!/bin/sh
set -eu
modify_path=1
case "${1:-}" in
    --no-modify-path) modify_path=0 ;;
    --help) printf '%s\n' 'Usage: install.sh [--no-modify-path]' 'Installs localizeit from GitHub for the current user; no sudo required.'; exit 0 ;;
    '') ;;
    *) printf '%s\n' 'Unknown option. Use --help.' >&2; exit 2 ;;
esac
release='https://github.com/Admin12121/Localize/releases/download/v3.2.3'
wheel='localizeit-3.2.3-py3-none-any.whl'
temporary=$(mktemp -d "${TMPDIR:-/tmp}/localizeit-install.XXXXXX")
trap 'rm -rf "$temporary"' EXIT
trap 'exit 1' HUP INT TERM
fetch() { curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --retry 2 "$1" --output "$2"; }
find_uv() {
    if command -v uv >/dev/null 2>&1; then command -v uv
    elif [ -n "${UV_UNMANAGED_INSTALL:-}" ] && [ -x "$UV_UNMANAGED_INSTALL/uv" ]; then printf '%s\n' "$UV_UNMANAGED_INSTALL/uv"
    elif [ -n "${CARGO_DIST_FORCE_INSTALL_DIR:-}" ] && [ -x "$CARGO_DIST_FORCE_INSTALL_DIR/uv" ]; then printf '%s\n' "$CARGO_DIST_FORCE_INSTALL_DIR/uv"
    elif [ -n "${UV_INSTALL_DIR:-}" ] && [ -x "$UV_INSTALL_DIR/uv" ]; then printf '%s\n' "$UV_INSTALL_DIR/uv"
    elif [ -x "$HOME/.local/bin/uv" ]; then printf '%s\n' "$HOME/.local/bin/uv"
    else return 1
    fi
}
if ! uv=$(find_uv); then
    printf '%s\n' 'Installing uv from its official installer (current user, no sudo)...'
    fetch 'https://astral.sh/uv/install.sh' "$temporary/uv-install.sh"
    if [ "$modify_path" -eq 0 ]; then
        UV_INSTALL_DIR="${UV_INSTALL_DIR:-$HOME/.local/bin}" UV_NO_MODIFY_PATH=1 sh "$temporary/uv-install.sh"
    else
        UV_INSTALL_DIR="${UV_INSTALL_DIR:-$HOME/.local/bin}" sh "$temporary/uv-install.sh"
    fi
    uv=$(find_uv) || { printf '%s\n' 'uv was not found after installation.' >&2; exit 1; }
fi
printf '%s\n' 'Downloading Localize v3.2.3 from GitHub and checking SHA-256...'
fetch "$release/SHA256SUMS" "$temporary/SHA256SUMS"
fetch "$release/$wheel" "$temporary/$wheel"
expected=$(awk -v name="$wheel" '$2==name {print $1}' "$temporary/SHA256SUMS")
if ! printf '%s\n' "$expected" | grep -Eq '^[a-f0-9]{64}$'; then
    printf '%s\n' 'The release has no unique SHA-256 checksum for the wheel.' >&2; exit 1
fi
if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$temporary/$wheel" | awk '{print $1}')
else
    actual=$(shasum -a 256 "$temporary/$wheel" | awk '{print $1}')
fi
if [ "$actual" != "$expected" ]; then
    printf '%s\n' 'Localize checksum verification failed. Nothing was installed.' >&2; exit 1
fi
printf '%s\n' 'Installing the localizeit command in an isolated Python environment...'
"$uv" tool install --force --python "${LOCALIZEIT_PYTHON:-3.12}" "$temporary/$wheel"
tool_directory=$("$uv" tool dir --bin)
"$tool_directory/localizeit" --about >/dev/null
if [ "$modify_path" -eq 1 ]; then "$uv" tool update-shell; fi
printf '%s\n' 'Localize is installed. Open a new terminal once, then run: localizeit'
