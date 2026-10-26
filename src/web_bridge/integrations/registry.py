"""Owner-configured skill roots and optional MCP adapters.

Only the local control surface may call configure. The companion separately checks
current grants before exposing reads/calls. No external application configuration
is imported. A session is opened per operation and closed on every outcome; calls
are never retried, since an interrupted call may already have made changes.
"""

import asyncio
from contextlib import AsyncExitStack
import copy
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit

from web_bridge.workspace.files import Workspace, WorkspaceError

MAX_RESPONSE = 256_000
MAX_ENTRIES = 100
MAX_CONFIG = 1_000_000


class IntegrationError(ValueError):
    pass


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value):
        raise IntegrationError(
            "Use a name containing letters, numbers, dots, underscores or hyphens."
        )
    return value


def _strings(value, label):
    if (
        not isinstance(value, dict)
        or len(value) > 100
        or any(
            not isinstance(k, str)
            or not isinstance(v, str)
            or not k
            or "\0" in k + v
            or len(k) > 200
            or len(v) > 16_000
            for k, v in value.items()
        )
    ):
        raise IntegrationError("Invalid local " + label + " configuration.")
    return dict(value)


class Integrations:
    def __init__(self, runtime):
        self.runtime = Path(runtime)
        self.path = self.runtime / "integrations.json"
        self.lock = threading.RLock()
        self.entries = []
        self.roots = {}
        self.closed = False
        if self.path.exists():
            try:
                if self.path.stat().st_size > MAX_CONFIG:
                    raise IntegrationError(
                        "Integration configuration exceeds its limit."
                    )
                entries = json.loads(self.path.read_text(encoding="utf-8"))
                self.entries, self.roots = self._validate(entries)
            except (OSError, ValueError):
                raise IntegrationError(
                    "Saved integrations are unavailable or invalid. Configure them again locally."
                ) from None

    def _validate(self, entries):
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            raise IntegrationError("Select at most 100 local integrations.")
        selected, roots, names = [], {}, set()
        for source in entries:
            if not isinstance(source, dict):
                raise IntegrationError("Each integration must be an object.")
            item = copy.deepcopy(source)
            name = _name(item.get("name"))
            if name in names:
                raise IntegrationError("Integration names must be unique.")
            names.add(name)
            kind = item.get("type")
            if kind == "skill":
                if set(item) - {"type", "name", "path"}:
                    raise IntegrationError("Unsupported skill configuration field.")
                path = item.get("path")
                if not isinstance(path, str) or not Path(path).is_absolute():
                    raise IntegrationError("Select an absolute local skill directory.")
                try:
                    root = Workspace(path, name)
                    root.read("SKILL.md")
                except (OSError, WorkspaceError):
                    raise IntegrationError(
                        "Select a trusted skill directory with a readable UTF-8 SKILL.md."
                    ) from None
                roots[name] = root
                item["path"] = str(root.root)
            elif kind == "mcp":
                common = {
                    "type",
                    "name",
                    "transport",
                    "enabled",
                    "enabled_tools",
                    "timeout",
                }
                if not isinstance(item.get("enabled", True), bool):
                    raise IntegrationError("Integration enabled must be true or false.")
                item["enabled"] = item.get("enabled", True)
                allowed = item.get("enabled_tools")
                if (
                    not isinstance(allowed, list)
                    or len(allowed) > 100
                    or any(
                        not isinstance(v, str) or not v or len(v) > 200 for v in allowed
                    )
                ):
                    raise IntegrationError(
                        "Select an explicit enabled_tools list; an empty list denies every tool."
                    )
                item["enabled_tools"] = list(dict.fromkeys(allowed))
                timeout = item.get("timeout", 30)
                if (
                    isinstance(timeout, bool)
                    or not isinstance(timeout, (float, int))
                    or not math.isfinite(timeout)
                    or not 0.1 <= timeout <= 120
                ):
                    raise IntegrationError(
                        "Integration timeout must be between 0.1 and 120 seconds."
                    )
                item["timeout"] = timeout
                transport = item.get("transport")
                if transport == "stdio":
                    if set(item) - common - {"command", "args", "env"}:
                        raise IntegrationError("Unsupported stdio configuration field.")
                    command, args = item.get("command"), item.get("args", [])
                    if (
                        not isinstance(command, str)
                        or not command
                        or len(command) > 2000
                        or "\0" in command
                    ):
                        raise IntegrationError("Select a local MCP executable.")
                    if (
                        not isinstance(args, list)
                        or len(args) > 100
                        or any(
                            not isinstance(v, str) or len(v) > 16_000 or "\0" in v
                            for v in args
                        )
                    ):
                        raise IntegrationError("Invalid local MCP arguments.")
                    item["args"] = args
                    item["env"] = _strings(item.get("env", {}), "environment")
                elif transport == "streamable_http":
                    if set(item) - common - {"url", "headers"}:
                        raise IntegrationError("Unsupported HTTP configuration field.")
                    url = item.get("url")
                    try:
                        parsed = urlsplit(url) if isinstance(url, str) else None
                        if (
                            not parsed
                            or parsed.scheme not in ("http", "https")
                            or not parsed.hostname
                            or parsed.username
                            or parsed.password
                            or parsed.fragment
                        ):
                            raise ValueError()
                        parsed.port
                    except ValueError:
                        raise IntegrationError(
                            "Select an HTTP or HTTPS MCP URL; keep credentials in local headers."
                        ) from None
                    item["headers"] = _strings(item.get("headers", {}), "HTTP headers")
                else:
                    raise IntegrationError("Select stdio or streamable_http transport.")
            else:
                raise IntegrationError("Select skill or mcp integration type.")
            selected.append(item)
        return selected, roots

    def configure(self, entries):
        with self.lock:
            self._open()
            selected, roots = self._validate(entries)
            serialized = json.dumps(selected)
            if len(serialized.encode("utf-8")) > MAX_CONFIG:
                raise IntegrationError(
                    "Integration configuration exceeds the 1 MB limit."
                )
            self.runtime.mkdir(parents=True, exist_ok=True)
            temporary = self.runtime / ("integrations-" + secrets.token_hex(8) + ".tmp")
            try:
                descriptor = os.open(
                    temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(serialized)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            except OSError:
                raise IntegrationError(
                    "Cannot save local integration configuration."
                ) from None
            finally:
                temporary.unlink(missing_ok=True)
            self.entries, self.roots = selected, roots
            return self.status()

    def _open(self):
        if self.closed:
            raise IntegrationError("Integration registry is closed.")

    def status(self):
        with self.lock:
            skills = [{"name": e["name"]} for e in self.entries if e["type"] == "skill"]
            servers = [
                {
                    k: e[k]
                    for k in (
                        "name",
                        "transport",
                        "enabled",
                        "enabled_tools",
                        "timeout",
                    )
                }
                for e in self.entries
                if e["type"] == "mcp"
            ]
            try:
                available = importlib.util.find_spec("mcp") is not None
            except (ValueError, ImportError):
                available = False
            return copy.deepcopy(
                {"skills": skills, "servers": servers, "mcp_available": available}
            )

    def skills(self):
        with self.lock:
            self._open()
            return {"skills": self.status()["skills"]}

    def skill_read(self, name, resource="SKILL.md"):
        with self.lock:
            self._open()
            if not isinstance(name, str) or name not in self.roots:
                raise IntegrationError("Skill is not selected locally.")
            try:
                result = self.roots[name].read(resource)
            except (OSError, WorkspaceError):
                raise IntegrationError(
                    "Skill resource is unavailable, unsafe, not UTF-8, or exceeds the 256 KB limit."
                ) from None
            return {
                "name": name,
                "resource": resource,
                "text": result["text"],
                "bytes": result["bytes"],
            }

    def _server(self, name):
        for item in self.entries:
            if item["type"] == "mcp" and item["name"] == name and item["enabled"]:
                return item
        raise IntegrationError("MCP server is not selected or is disabled locally.")

    def tools(self, server=None):
        with self.lock:
            self._open()
            entries = (
                [self._server(server)]
                if server is not None
                else [e for e in self.entries if e["type"] == "mcp" and e["enabled"]]
            )
            tools = []
            for item in entries:
                if item["enabled_tools"]:
                    tools.extend(self._request(item, "tools"))
            return self._bounded({"tools": tools})

    def call(self, server, tool, arguments):
        with self.lock:
            self._open()
            item = self._server(server)
            if not isinstance(tool, str) or tool not in item["enabled_tools"]:
                raise IntegrationError("MCP tool is not enabled locally.")
            if not isinstance(arguments, dict):
                raise IntegrationError("MCP arguments must be an object.")
            self._bounded(arguments)
            return self._request(item, "call", tool, copy.deepcopy(arguments))

    def _bounded(self, result):
        try:
            data = json.dumps(result, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            raise IntegrationError("MCP data must be bounded JSON.") from None
        if len(data.encode("utf-8")) > MAX_RESPONSE:
            raise IntegrationError("MCP data exceeds the 256 KB limit.")
        return result

    def _redact(self, item, result):
        values = list(item.get("env", {}).values()) + list(
            item.get("headers", {}).values()
        )
        values += [
            v.split(" ", 1)[1] for v in values if v.lower().startswith("bearer ")
        ]

        def visit(value):
            if isinstance(value, str):
                for secret in values:
                    if secret:
                        value = value.replace(secret, "[redacted]")
                return value
            if isinstance(value, list):
                return [visit(v) for v in value]
            if isinstance(value, dict):
                return {visit(k): visit(v) for k, v in value.items()}
            return value

        return visit(result)

    def _request(self, item, operation, tool=None, arguments=None):
        try:
            from mcp import Client
            from mcp.client.stdio import stdio_client, StdioServerParameters
            from mcp.client.streamable_http import streamable_http_client
            import anyio
            import httpx2
            from jsonschema import Draft202012Validator
            from referencing import Registry
        except ImportError:
            raise IntegrationError(
                "MCP requires Python 3.11+ and the optional requirements-integrations.txt dependencies."
            ) from None

        async def run():
            # SDK contexts own transport cleanup. Cancellation covers connection,
            # discovery and call; no replay or automatic approval callbacks.
            with anyio.fail_after(item["timeout"]):
                async with AsyncExitStack() as stack:
                    if item["transport"] == "stdio":
                        errlog = stack.enter_context(open(os.devnull, "w"))
                        parameters = StdioServerParameters(
                            command=item["command"], args=item["args"], env=item["env"]
                        )
                        transport = stdio_client(parameters, errlog=errlog)
                    else:
                        http = await stack.enter_async_context(
                            httpx2.AsyncClient(
                                headers=item["headers"],
                                timeout=item["timeout"],
                                follow_redirects=False,
                                trust_env=False,
                            )
                        )
                        transport = streamable_http_client(
                            item["url"], http_client=http
                        )
                    async with Client(
                        transport, read_timeout_seconds=item["timeout"], cache=None
                    ) as client:
                        selected = []
                        cursor = None
                        for _ in range(10):
                            listing = await client.list_tools(cursor=cursor)
                            for discovered in listing.tools:
                                if discovered.name in item["enabled_tools"]:
                                    selected.append(
                                        {
                                            "server": item["name"],
                                            "name": discovered.name,
                                            "description": discovered.description or "",
                                            "inputSchema": discovered.input_schema,
                                        }
                                    )
                            cursor = listing.next_cursor
                            if not cursor:
                                break
                        else:
                            raise IntegrationError(
                                "MCP discovery exceeds the pagination limit."
                            )
                        self._bounded(selected)
                        if operation == "tools":
                            return selected
                        advertised = next(
                            (v for v in selected if v["name"] == tool), None
                        )
                        if advertised is None:
                            raise IntegrationError(
                                "Enabled MCP tool was not advertised by the selected server."
                            )
                        try:
                            schema = advertised["inputSchema"]
                            Draft202012Validator.check_schema(schema)
                            # No implicit network or filesystem retrieval for a
                            # server-supplied $ref; local definitions still work.
                            Draft202012Validator(schema, registry=Registry()).validate(
                                arguments
                            )
                        except Exception:
                            raise IntegrationError(
                                "MCP arguments or the selected tool schema are invalid or unsupported."
                            ) from None
                        # The high-level Client.call_tool retries HEADER_MISMATCH
                        # and drives input-required rounds. Use the SDK session's
                        # single request, so an uncertain side effect never repeats.
                        result = await client.session.call_tool(tool, arguments)
                        return {
                            "server": item["name"],
                            "tool": tool,
                            **result.model_dump(
                                mode="json", by_alias=True, exclude_none=True
                            ),
                        }

        try:
            return self._bounded(self._redact(item, asyncio.run(run())))
        except IntegrationError:
            raise
        except TimeoutError:
            raise IntegrationError(
                "MCP operation timed out; its effects may be uncertain. Check locally before retrying."
            ) from None
        except Exception as exc:
            # anyio transport task groups may wrap our safe validation errors.
            pending = [exc]
            for _ in range(64):
                if not pending:
                    break
                problem = pending.pop()
                if isinstance(problem, IntegrationError):
                    raise IntegrationError(str(problem)) from None
                if isinstance(problem, TimeoutError):
                    raise IntegrationError(
                        "MCP operation timed out; its effects may be uncertain. Check locally before retrying."
                    ) from None
                pending.extend(getattr(problem, "exceptions", ()))
            # Never echo SDK exceptions: they can contain URLs, headers, arguments
            # and remote error data. Raw subprocess stderr is discarded above.
            raise IntegrationError(
                "MCP operation failed. Check the locally selected adapter and optional SDK installation."
            ) from None

    def close(self):
        with self.lock:
            self.closed = True
