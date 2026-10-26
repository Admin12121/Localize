"""MCP dispatch and stdio transport, backed by the shared tool contract."""

import json
import sys
from web_bridge.web.policy import BridgeError
from web_bridge.resources import TOOL_DEFINITIONS
from web_bridge.security.oauth import SCOPE

VERSION = "2.0.0"
SCHEMAS = {
    tool["name"]: (
        tool["description"],
        tool["inputSchema"]["properties"],
        tool["inputSchema"].get("required", []),
    )
    for tool in TOOL_DEFINITIONS
}


def rpc(message, bridge):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": message.get("id") if isinstance(message, dict) else None,
            "error": {"code": -32600, "message": "Invalid Request"},
        }
    if "id" not in message:
        return None
    req_id = message["id"]
    name = message.get("method")
    try:
        if name == "initialize":
            client_protocol = message.get("params", {}).get(
                "protocolVersion", "2025-03-26"
            )
            protocol = (
                client_protocol
                if client_protocol in ("2025-06-18", "2025-03-26", "2024-11-05")
                else "2025-06-18"
            )
            data = {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ctf-instance-bridge", "version": VERSION},
            }
        elif name == "ping":
            data = {}
        elif name == "tools/list":
            data = {
                "tools": [
                    {
                        "name": k,
                        "description": desc,
                        "inputSchema": {
                            "type": "object",
                            "properties": fields,
                            "required": required,
                            "additionalProperties": False,
                        },
                        "securitySchemes": [{"type": "oauth2", "scopes": [SCOPE]}],
                    }
                    for k, (desc, fields, required) in SCHEMAS.items()
                ]
            }
        elif name == "tools/call":
            params = message.get("params", {})
            tool = params.get("name")
            args = params.get("arguments") or {}
            if tool not in SCHEMAS:
                raise BridgeError("Unknown tool")
            if not isinstance(args, dict):
                raise BridgeError("arguments must be an object")
            allowed = set(SCHEMAS[tool][1])
            if set(args) - allowed:
                raise BridgeError(
                    "Unexpected argument(s): " + ",".join(sorted(set(args) - allowed))
                )
            missing = set(SCHEMAS[tool][2]) - set(args)
            if missing:
                raise BridgeError("Missing: " + ",".join(sorted(missing)))
            result = getattr(bridge, tool)(**args)
            data = {
                "content": [
                    {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                ],
                "isError": bool(result.get("error"))
                or result.get("isError") is True
                or result.get("state")
                in ("failed", "timed_out", "interrupted", "denied", "expired"),
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "Method not found"},
            }
        return {"jsonrpc": "2.0", "id": req_id, "result": data}
    except Exception as exc:
        if name == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32603, "message": str(exc)},
        }


def serve_stdio(bridge):
    for line in sys.stdin:
        try:
            message = json.loads(line)
            result = rpc(message, bridge)
            if result is not None:
                sys.stdout.write(
                    json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
                sys.stdout.flush()
        except Exception as exc:
            print(f"MCP error: {exc}", file=sys.stderr)
