"""Prepare the official tunnel in a private cache; never execute an unchecked download."""

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import re
import tarfile
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from web_bridge.runtime import runtime_home
from web_bridge.workspace.files import linked

RELEASE_URL = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
MAX_DOWNLOAD = 128 * 1024 * 1024


class SetupError(ValueError):
    pass


def asset_name(system, machine):
    arch = {
        "amd64": "amd64",
        "x86_64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine.lower())
    os_name = {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}.get(system)
    if not arch or not os_name or (system == "Windows" and arch != "amd64"):
        raise SetupError(
            "Install cloudflared manually for this architecture, or use --local-only."
        )
    suffix = ".exe" if system == "Windows" else ".tgz" if system == "Darwin" else ""
    return f"cloudflared-{os_name}-{arch}{suffix}"


def _cache_root(cache_root):
    return Path(
        cache_root or runtime_home().parent / "tools" / "cloudflared"
    ).absolute()


def _reject_links(path):
    for item in (path, *path.parents):
        try:
            if linked(item.lstat()):
                raise SetupError(
                    "Tunnel cache contains a linked path. Choose a regular private cache location."
                )
        except FileNotFoundError:
            pass


def cached_cloudflared(cache_root=None, *, system=None, machine=None):
    root = _cache_root(cache_root)
    _reject_links(root)
    system, machine = system or platform.system(), machine or platform.machine()
    binary = root / ("cloudflared.exe" if system == "Windows" else "cloudflared")
    record = root / "install.json"
    _reject_links(binary)
    _reject_links(record)
    try:
        if (
            record.stat().st_size > 16_384
            or not binary.is_file()
            or binary.stat().st_size > MAX_DOWNLOAD
        ):
            return None
        metadata = json.loads(record.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or metadata.get("asset") != asset_name(
            system, machine
        ):
            return None
        if hashlib.sha256(binary.read_bytes()).hexdigest() != metadata.get(
            "binary_sha256"
        ):
            return None
        return binary
    except (OSError, ValueError):
        return None


def _read(url, limit, opener, timeout):
    request = Request(
        url,
        headers={
            "User-Agent": "Localize-Web-Bridge",
            "Accept": (
                "application/json" if url == RELEASE_URL else "application/octet-stream"
            ),
        },
    )
    with opener(request, timeout=timeout) as response:
        final = urlsplit(response.geturl())
        if final.scheme != "https" or not (
            final.hostname in ("api.github.com", "github.com")
            or (final.hostname or "").endswith(".githubusercontent.com")
        ):
            raise SetupError(
                "Tunnel download did not remain on an official HTTPS release host."
            )
        data = response.read(limit + 1)
    if len(data) > limit:
        raise SetupError("Tunnel download exceeds the size limit.")
    return data


def _unpack(data):
    candidates = []
    total = 0
    with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as archive:
        for count, member in enumerate(archive):
            total += member.size
            if count >= 100 or total > MAX_DOWNLOAD:
                raise SetupError("Tunnel archive exceeds its limit.")
            if member.name in ("cloudflared", "./cloudflared"):
                if not member.isfile():
                    raise SetupError("Tunnel archive binary must be a regular file.")
                stream = archive.extractfile(member)
                if stream is None:
                    raise SetupError("Tunnel archive has no readable binary.")
                with stream:
                    candidates.append(stream.read(MAX_DOWNLOAD + 1))
    if len(candidates) != 1 or not candidates[0] or len(candidates[0]) > MAX_DOWNLOAD:
        raise SetupError("Tunnel archive has no single expected binary.")
    return candidates[0]


def _atomic(path, data, mode):
    descriptor, temporary = tempfile.mkstemp(prefix=".prepare-", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_cloudflared(
    cache_root=None, *, system=None, machine=None, opener=None, report=print
):
    system, machine = system or platform.system(), machine or platform.machine()
    cached = cached_cloudflared(cache_root, system=system, machine=machine)
    if cached:
        return cached
    name = asset_name(system, machine)
    root = _cache_root(cache_root)
    _reject_links(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    report("Preparing the official Cloudflare tunnel in your local cache...")
    try:
        metadata = json.loads(_read(RELEASE_URL, 2_000_000, opener or urlopen, 20))
        release = metadata["tag_name"]
        if not isinstance(release, str) or not re.fullmatch(
            r"[A-Za-z0-9._-]{1,64}", release
        ):
            raise SetupError("Invalid official tunnel release metadata.")
        item = next((item for item in metadata["assets"] if item["name"] == name), None)
        if item is None:
            raise SetupError(
                "The official release has no binary for this platform. Install cloudflared manually."
            )
        digest = item.get("digest", "")
        if not isinstance(digest, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", digest
        ):
            raise SetupError(
                "The official release has no usable checksum; no executable was installed."
            )
        url = f"https://github.com/cloudflare/cloudflared/releases/download/{release}/{name}"
        if item.get("browser_download_url") != url:
            raise SetupError(
                "Tunnel binary URL is not the expected official release URL."
            )
        size = item["size"]
        if type(size) is not int or not 0 < size <= MAX_DOWNLOAD:
            raise SetupError("Tunnel download exceeds the size limit.")
        data = _read(url, size, opener or urlopen, 60)
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest.removeprefix(
            "sha256:"
        ):
            raise SetupError(
                "Tunnel checksum verification failed; no executable was installed."
            )
        binary_data = _unpack(data) if name.endswith(".tgz") else data
        binary = root / ("cloudflared.exe" if system == "Windows" else "cloudflared")
        _reject_links(binary)
        _reject_links(root / "install.json")
        record = {
            "asset": name,
            "release": release,
            "download_sha256": digest,
            "binary_sha256": hashlib.sha256(binary_data).hexdigest(),
        }
        _atomic(binary, binary_data, 0o700)
        _atomic(root / "install.json", (json.dumps(record) + "\n").encode(), 0o600)
        report(f"Verified cloudflared {release}; cached for future launches.")
        return binary
    except SetupError:
        raise
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError):
        raise SetupError(
            "Could not prepare the official tunnel. Check connectivity, install cloudflared manually, or use --local-only."
        ) from None
