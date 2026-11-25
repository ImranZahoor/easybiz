from __future__ import annotations

import json

from ninja import Router

from easybiz.core.api.agent_auth import tool_principal
from easybiz.core.api.types import ToolDetailOut, ToolSummaryOut
from easybiz.core.tools import service
from easybiz.core.tools.registry import registry

router = Router()


@router.get("", auth=tool_principal, response=list[ToolSummaryOut])
def list_tools(request, q: str = ""):
    """Tools the caller (user or agent key) may use (compact; load schemas lazily via describe)."""
    tools = service.accessible_for(request.auth)
    if q:
        ql = q.lower()
        tools = [t for t in tools if ql in t.name.lower() or ql in t.description.lower()]
    return [ToolSummaryOut(name=t.name, description=t.description, tier=t.tier) for t in tools]


@router.get("/{name}", auth=tool_principal, response=ToolDetailOut)
def describe_tool(request, name: str):
    """The tool's input schema, permission, and tier (only if the caller may use it)."""
    tool = registry.get(name)
    if tool is None:
        raise service.ToolError(f"unknown tool {name!r}", 404)
    if not service._enabled(tool):
        raise service.ToolError(
            f"tool {name!r} is not available", 404
        )  # disabled module → gate 404
    if tool not in service.accessible_for(request.auth):
        raise service.ToolError(f"missing permission {tool.perm!r}", 403)
    return ToolDetailOut(**service.describe(tool))


@router.post("/{name}/invoke", auth=tool_principal)
def invoke_tool(request, name: str):
    """Invoke a tool with a JSON body; allowlist/scope/perm/validation enforced by the service."""
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise service.ToolError("invalid JSON body", 422) from exc
    return service._invoke(name, body, request.auth)
