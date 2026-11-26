from __future__ import annotations

import json

from django.http import HttpResponse
from ninja import Router

from easybiz.core.api.agent_auth import tool_principal
from easybiz.core.mcp import protocol

router = Router()


@router.post("", auth=tool_principal)
def rpc(request):
    """A single JSON-RPC 2.0 message over streamable-HTTP MCP.

    Auth (tenant JWT user or scoped agent key → Principal) and tenant resolution
    are handled by ``tool_principal`` + the tenant middleware before we get here,
    so the handshake itself is authenticated. The dispatch core enforces the gate.
    """
    try:
        message = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
    response = protocol.handle_message(message, request.auth)
    if response is None:
        return HttpResponse(status=202)  # a notification: accepted, no body
    return response
