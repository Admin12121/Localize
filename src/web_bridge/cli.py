#!/usr/bin/env python3
"""Cross-platform launcher. Local controls and authenticated RPC are separate listeners."""

import argparse
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from web_bridge.web.client import Bridge
from web_bridge.transport.http import BoundedHTTPServer, handler_factory
from web_bridge.app import Companion
from web_bridge.transport.control import ControlServer
from web_bridge.security.oauth import OAuth
from web_bridge.resources import PROJECT, VERSION
from web_bridge.runtime import runtime_home


def find_cloudflared():
    installed = shutil.which("cloudflared")
    if installed:
        return installed
    # Fresh installs may not be visible in the current terminal's PATH yet.
    candidates = [
        Path("/opt/homebrew/bin/cloudflared"),
        Path("/usr/local/bin/cloudflared"),
    ]
    if os.name == "nt":
        for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(key)
            if base:
                candidates.extend(
                    [
                        Path(base) / "cloudflared/cloudflared.exe",
                        Path(base) / "Microsoft/WinGet/Links/cloudflared.exe",
                    ]
                )
    found = next((str(p) for p in candidates if p.is_file()), None)
    if found:
        return found
    from web_bridge.setup.tunnel import cached_cloudflared

    return cached_cloudflared()


def private_file(path, create):
    if path.is_symlink():
        raise ValueError("Runtime credential cannot be a symlink.")
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(create())
    os.chmod(path, 0o600)
    return path.read_text().strip()


def secure_runtime(path):
    if path.is_symlink():
        raise ValueError("Runtime directory cannot be a symlink.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    if os.name == "nt":
        # A user-only DACL protects persistent keys; POSIX chmod alone cannot do this on Windows.
        import ctypes
        from ctypes import wintypes

        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        adv.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        adv.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        token = wintypes.HANDLE()
        if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise ValueError("Unable to protect local credentials.")
        try:
            needed = wintypes.DWORD()
            adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            data = ctypes.create_string_buffer(needed.value)
            if not adv.GetTokenInformation(
                token, 1, data, needed, ctypes.byref(needed)
            ):
                raise ValueError("Unable to identify local credential owner.")
            sid = ctypes.c_void_p.from_buffer(data).value
            sid_string = wintypes.LPWSTR()
            adv.ConvertSidToStringSidW.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.LPWSTR),
            ]
            if not adv.ConvertSidToStringSidW(sid, ctypes.byref(sid_string)):
                raise ValueError("Unable to identify credential owner.")
            try:
                sddl = f"D:P(A;OICI;FA;;;{sid_string.value})(A;OICI;FA;;;SY)"
            finally:
                kernel.LocalFree(sid_string)
            descriptor = ctypes.c_void_p()
            adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.c_void_p,
            ]
            if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None
            ):
                raise ValueError("Unable to protect credentials.")
            try:
                adv.SetFileSecurityW.argtypes = [
                    wintypes.LPCWSTR,
                    wintypes.DWORD,
                    ctypes.c_void_p,
                ]
                if not adv.SetFileSecurityW(str(path), 0x80000004, descriptor):
                    raise ValueError("Unable to set private credential permissions.")
            finally:
                kernel.LocalFree(descriptor)
        finally:
            kernel.CloseHandle(token)


def parse_options(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Admin12211's Web-Bridge instance — Windows, macOS, Linux"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Web-Bridge "
        + VERSION
        + " · by "
        + PROJECT["creator"]
        + " · "
        + PROJECT["license"],
    )
    parser.add_argument(
        "--about",
        action="store_true",
        help="Show public author, license and platform metadata, then exit",
    )
    parser.add_argument(
        "--target",
        help="One explicitly approved CTF origin; more can be configured locally",
    )
    network = parser.add_mutually_exclusive_group()
    network.add_argument(
        "--tunnel",
        action="store_true",
        help="Expose authenticated RPC with an installed cloudflared Quick Tunnel",
    )
    network.add_argument(
        "--local-only",
        action="store_true",
        help="Keep the companion on this computer without a tunnel",
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--runtime", type=Path, default=runtime_home())
    parser.add_argument("--rpc-port", type=int, default=8765)
    parser.add_argument("--control-port", type=int, default=8766)
    return parser.parse_args(argv)


def main(argv=None, *, tunnel_binary=None):
    options = parse_options(argv)
    if options.about:
        import json

        print(json.dumps(PROJECT, indent=2))
        return
    runtime = options.runtime.absolute()
    secure_runtime(runtime)
    key = private_file(
        runtime / "site-connection-key", lambda: secrets.token_urlsafe(48)
    )
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,160}", key):
        raise ValueError("Invalid saved key. Rotate the key locally before starting.")
    pin = private_file(runtime / "oauth-pin", lambda: secrets.token_urlsafe(24))
    public = runtime / "public-url"
    public.write_text("")
    network = Bridge({"challenge": options.target} if options.target else {})
    companion = Companion(network, runtime / "jobs")
    owner_code = secrets.token_urlsafe(18)
    auth = OAuth(pin, url_file=str(public))
    rpc = BoundedHTTPServer(
        ("127.0.0.1", options.rpc_port), handler_factory(companion, auth, set(), key)
    )
    try:
        control = ControlServer(companion, owner_code, options.control_port)
    except Exception:
        rpc.server_close()
        companion.close()
        raise
    threading.Thread(target=rpc.serve_forever, daemon=True).start()
    threading.Thread(target=control.serve_forever, daemon=True).start()
    local = f"http://127.0.0.1:{control.server_port}"
    tunnel = None
    log = None
    try:
        print("\n" + PROJECT["display_name"] + " · companion " + VERSION, flush=True)
        print(
            "Created by " + PROJECT["creator"] + " · " + PROJECT["license"], flush=True
        )
        print("LOCAL CONTROL PANEL: " + local, flush=True)
        print("LOCAL CONTROL CODE: " + owner_code, flush=True)
        print(
            "Coding access is disabled until you select a project and permissions locally.",
            flush=True,
        )
        if not options.no_browser:
            webbrowser.open(local)
        if options.tunnel:
            cloudflared = tunnel_binary or find_cloudflared()
            if not cloudflared:
                raise ValueError(
                    "Install cloudflared first. Windows: winget install Cloudflare.cloudflared; macOS: brew install cloudflared; Linux: use the official Cloudflare package."
                )
            logpath = runtime / "cloudflared.log"
            log = logpath.open("w", encoding="utf-8")
            tunnel = subprocess.Popen(
                [cloudflared, "tunnel", "--url", f"http://127.0.0.1:{rpc.server_port}"],
                stdout=log,
                stderr=subprocess.STDOUT,
                **(
                    {"creationflags": subprocess.CREATE_NO_WINDOW}
                    if os.name == "nt"
                    else {}
                ),
            )
            deadline = time.monotonic() + 90
            endpoint = ""
            while time.monotonic() < deadline:
                if tunnel.poll() is not None:
                    raise ValueError(
                        "cloudflared stopped. Inspect its private runtime log."
                    )
                text = logpath.read_text(encoding="utf-8", errors="replace")
                match = re.search(
                    r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com", text
                )
                if match:
                    endpoint = match.group()
                    break
                time.sleep(0.5)
            if not endpoint:
                raise ValueError("Timed out waiting for the tunnel address.")
            public.write_text(endpoint)
            print("SITE ENDPOINT: " + endpoint + "/mcp", flush=True)
            print("SITE CONNECTION KEY: " + key, flush=True)
            print(
                "Save the endpoint and key in your private Site. Keep both local codes and keys out of chat.",
                flush=True,
            )
        else:
            print(
                "Local-only launch. Add --tunnel when you are ready to connect your private Site.",
                flush=True,
            )
        print(
            "Keep this terminal open. Ctrl+C stops owned jobs and the tunnel.",
            flush=True,
        )
        while True:
            if tunnel and tunnel.poll() is not None:
                raise ValueError(
                    "Tunnel stopped; reconnect after restarting the companion."
                )
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        companion.close()
        rpc.shutdown()
        rpc.server_close()
        control.shutdown()
        control.server_close()
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()
        if log:
            log.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Companion stopped: " + str(exc), file=sys.stderr)
        sys.exit(1)
