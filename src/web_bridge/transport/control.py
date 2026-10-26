"""Separate loopback-only owner controls. Never route this listener through a tunnel."""

from collections import deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
import hmac
import hashlib
import json
import secrets
import subprocess
import sys
import time
from urllib.parse import urlsplit, parse_qs
from web_bridge.workspace.files import WorkspaceError
from web_bridge.transport.http import BoundedHTTPServer


CONTROL_PAGES = frozenset({
    "/", "/overview", "/workspace", "/docker", "/connections",
    "/activity", "/agent",
})


class ControlServer(BoundedHTTPServer):
    daemon_threads = True

    def __init__(self, companion, code, port=8766):
        self.companion = companion
        self.code = code
        self.session = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(32)
        self.attempts = deque(maxlen=10)
        super().__init__(("127.0.0.1", port), ControlHandler)


class ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def send(self, status, data, content_type="application/json", headers=None):
        body = (
            json.dumps(data).encode()
            if isinstance(data, dict)
            else data.encode() if isinstance(data, str) else data
        )
        self.send_response(status)
        for name, value in {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            **(headers or {}),
        }.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def gate(self, write=False, login=False):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            raise PermissionError("Unexpected local Host.")
        request_origin = self.headers.get("Origin")
        if (write and request_origin != origin) or (
            request_origin and request_origin != origin
        ):
            raise PermissionError("Local controls require their own origin.")
        if login:
            return
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        actual = cookie.get("web_bridge_owner")
        if not actual or not hmac.compare_digest(actual.value, self.server.session):
            raise LookupError("Sign in using the local code printed by the companion.")
        if write and not hmac.compare_digest(
            self.headers.get("X-Web-Bridge-CSRF", ""), self.server.csrf
        ):
            raise PermissionError("Refresh the local control panel and try again.")

    def do_GET(self):
        try:
            route = urlsplit(self.path)
            self.gate(login=route.path in CONTROL_PAGES)
            if route.path in CONTROL_PAGES:
                from web_bridge.resources import UI_ROOT

                root = UI_ROOT
                page = (
                    (root / "control.html")
                    .read_text(encoding="utf-8")
                    .replace("__STYLE__", (root / "ui.css").read_text(encoding="utf-8"))
                )
                return self.send(200, page, "text/html; charset=utf-8")
            if self.path == "/api/state":
                state = self.server.companion.local_state()
                etag = (
                    '"'
                    + hashlib.sha256(
                        json.dumps(state, sort_keys=True).encode()
                    ).hexdigest()
                    + '"'
                )
                if self.headers.get("If-None-Match") == etag:
                    return self.send(304, b"", headers={"ETag": etag})
                return self.send(200, state, headers={"ETag": etag})
            if route.path == "/api/docker/status":
                return self.send(
                    200,
                    self.server.companion.local_docker_status(),
                )
            if route.path == "/api/task":
                return self.send(
                    200,
                    self.server.companion.task_read(
                        parse_qs(route.query).get("id", [""])[0],
                        workspace_id=self.server.companion.workspace_id,
                    ),
                )
            if route.path in ("/api/job", "/api/edit"):
                key = parse_qs(route.query).get("id", [""])[0]
                if len(key) > 64:
                    raise ValueError("Invalid operation ID.")
                result = (
                    self.server.companion.jobs.status(key)
                    if route.path == "/api/job"
                    else self.server.companion.local_edit(key)
                )
                return self.send(200, result)
            return self.send(404, {"error": "Not found"})
        except LookupError as exc:
            self.send(401, {"error": str(exc)})
        except PermissionError as exc:
            self.send(403, {"error": str(exc)})
        except Exception:
            self.send(400, {"error": "Local request failed."})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if (
                not 0 < length <= 400_000
                or self.headers.get("Content-Type", "").split(";")[0]
                != "application/json"
            ):
                raise WorkspaceError("Use bounded JSON input.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise WorkspaceError("Expected an object.")
            login = self.path == "/api/login"
            self.gate(write=True, login=login)
            companion = self.server.companion
            if login:
                now = time.monotonic()
                if sum(now - t < 60 for t in self.server.attempts) >= 5:
                    raise PermissionError("Too many attempts. Wait one minute.")
                if not isinstance(data.get("code"), str) or not hmac.compare_digest(
                    data["code"], self.server.code
                ):
                    self.server.attempts.append(now)
                    raise PermissionError("Incorrect local code.")
                return self.send(
                    200,
                    {"csrf": self.server.csrf},
                    headers={
                        "Set-Cookie": f"web_bridge_owner={self.server.session}; HttpOnly; SameSite=Strict; Path=/"
                    },
                )
            if self.path == "/api/configure":
                targets = data.get("targets", {})
                if type(data.get("allow_private", False)) is not bool:
                    raise WorkspaceError("Invalid private-target permission.")
                result = companion.configure(
                    root=data.get("root", ""),
                    alias=data.get("alias", "workspace"),
                    targets=targets,
                    allow_private=data.get("allow_private", False),
                    profile=data.get("profile"),
                    **data.get("permissions", {}),
                )
                return self.send(200, result)
            if self.path == "/api/docker/configure":
                return self.send(200, companion.configure_docker(data))
            if self.path == "/api/docker/action":
                action = data.pop("action", None)
                return self.send(200, companion.docker_action(action, **data))
            if self.path == "/api/integrations/add":
                return self.send(200, companion.integration_add(data.get("entry")))
            if self.path == "/api/integrations/remove":
                return self.send(200, companion.integration_remove(data.get("name")))
            if self.path == "/api/runner/configure":
                return self.send(200, companion.configure_runner(data))
            if self.path == "/api/runner/start":
                return self.send(200, companion.start_runner(data.get("task_id")))
            if self.path == "/api/runner/cancel":
                return self.send(200, companion.cancel_runner(data.get("task_id")))
            if self.path == "/api/job/review-stopped":
                return self.send(
                    200, companion.acknowledge_command_recovery(data.get("job_id"))
                )
            if self.path == "/api/task/complete":
                return self.send(
                    200, companion.complete_task_locally(data.get("task_id"))
                )
            if self.path == "/api/task/resume":
                return self.send(200, companion.resume_task(data.get("task_id")))
            if self.path == "/api/artifact/remove":
                return self.send(200, companion.discard_artifact(data.get("job_id")))
            if self.path == "/api/task/create":
                return self.send(
                    200,
                    companion.task_create(
                        data.get("intent"),
                        data.get("checks"),
                        workspace_id=companion.workspace_id,
                    ),
                )
            if self.path == "/api/choose-folder":
                script = "import tkinter as t;from tkinter import filedialog;r=t.Tk();r.withdraw();print(filedialog.askdirectory(title='Choose a project folder for Web-Bridge'));r.destroy()"
                import os

                result = subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    **(
                        {"creationflags": subprocess.CREATE_NO_WINDOW}
                        if os.name == "nt"
                        else {}
                    ),
                )
                if result.returncode:
                    raise WorkspaceError(
                        "Folder picker unavailable. Enter the project path locally instead."
                    )
                return self.send(200, {"path": result.stdout.strip()})
            if self.path == "/api/pause":
                if type(data.get("paused")) is not bool:
                    raise WorkspaceError("Invalid pause setting.")
                return self.send(200, companion.pause(data["paused"]))
            if self.path == "/api/edit":
                return self.send(
                    200,
                    companion.approve_edit(
                        data.get("edit_id"), data.get("allow") is True
                    ),
                )
            if self.path == "/api/command":
                return self.send(
                    200,
                    companion.approve_command(
                        data.get("job_id"), data.get("allow") is True
                    ),
                )
            if self.path == "/api/cancel":
                return self.send(200, companion.command_cancel(data.get("job_id")))
            return self.send(404, {"error": "Not found"})
        except LookupError as exc:
            self.send(401, {"error": str(exc)})
        except PermissionError as exc:
            self.send(403, {"error": str(exc)})
        except (WorkspaceError, ValueError, TypeError) as exc:
            self.send(400, {"error": str(exc)[:1000] or "Invalid local operation."})
        except Exception:
            self.send(
                400, {"error": "Local operation failed; check prerequisites and retry."}
            )
