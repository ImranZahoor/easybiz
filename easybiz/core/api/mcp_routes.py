from __future__ import annotations

import json

from django.http import HttpResponse
from ninja import Router

from easybiz.core.api.agent_auth import tool_principal
from easybiz.core.mcp import protocol

router = Router()


@router.post("", auth=tool_principal)
def rpc(request):
    """Handle one JSON-RPC 2.0 message over streamable-HTTP MCP."""
    try:
        message = json.loads(request.body or b"{}")
    except (ValueError, RecursionError):
        # JSONDecodeError (a ValueError) for bad JSON; RecursionError for pathologically deep input
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
    response = protocol.handle_message(message, request.auth)
    if response is None:
        return HttpResponse(status=202)  # a notification: accepted, no body
    return response
