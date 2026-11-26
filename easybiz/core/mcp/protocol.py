"""Transport-free JSON-RPC 2.0 dispatch for the Model Context Protocol.

One parsed message + a tool :class:`Principal` in, one JSON-RPC response dict
out (or ``None`` for a notification). ``tools/list`` and ``tools/call`` delegate
to the shared tool service, so the F23b gate and audit are inherited unchanged —
this layer adds no tool logic and no new way to authorize. HTTP framing lives in
the route; this module never touches the request.
"""

from __future__ import annotations

import json

from django.conf import settings

from easybiz.core.errors import DomainError
from easybiz.core.tools import service
from easybiz.core.tools.registry import Tool

PROTOCOL_VERSION = "2025-06-18"

# JSON-RPC 2.0 error codes
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602


def _server_info() -> dict:
    # read the setting live rather than freezing it at import time
    return {"name": "easybiz", "version": settings.EASYBIZ_CORE_VERSION}


def _result(id_, result) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def tool_descriptor(tool: Tool) -> dict:
    """An MCP tool entry: name, description, and the input schema as JSON Schema."""
    if tool.input_schema is not None:
        schema = tool.input_schema.model_json_schema()
    else:
        schema = {"type": "object", "properties": {}}
    return {"name": tool.name, "description": tool.description, "inputSchema": schema}


def handle_message(message, principal) -> dict | None:
    """Dispatch one JSON-RPC message. Returns a response dict, or None for a notification.

    Protocol-level problems (bad shape, unknown method, bad params) become JSON-RPC
    errors; a tool-gate denial from ``_invoke`` becomes an ``isError`` result, per the
    MCP convention that tool failures are results, not protocol errors.
    """
    if not isinstance(message, dict) or not isinstance(message.get("method"), str):
        mid = message.get("id") if isinstance(message, dict) else None
        return _error(mid, _INVALID_REQUEST, "invalid request")

    # A message without an id is a notification: act (no-op here) and send nothing back.
    if "id" not in message:
        return None

    id_ = message["id"]
    method = message["method"]

    if method == "initialize":
        return _result(
            id_,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": _server_info(),
            },
        )
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        tools = [tool_descriptor(t) for t in service.accessible_for(principal)]
        return _result(id_, {"tools": tools})
    if method == "tools/call":
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(id_, _INVALID_PARAMS, "params must be an object")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _error(id_, _INVALID_PARAMS, "missing tool name")
        arguments = params.get("arguments") or {}
        try:
            result = service._invoke(name, arguments, principal)
        except DomainError as exc:
            return _result(id_, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        text = json.dumps(result, default=str)
        return _result(id_, {"content": [{"type": "text", "text": text}], "isError": False})

    return _error(id_, _METHOD_NOT_FOUND, f"method not found: {method}")
