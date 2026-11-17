from __future__ import annotations

import json

from ninja import Router

from easybiz.core.api.security import authenticated
from easybiz.core.api.types import ToolDetailOut, ToolSummaryOut
from easybiz.core.tools import service
from easybiz.core.tools.registry import registry

router = Router()


@router.get("", auth=authenticated, response=list[ToolSummaryOut])
def list_tools(request, q: str = ""):
    """Tools the caller is authorized for (compact; load schemas lazily via describe)."""
    tools = service.accessible(request.auth.id)
    if q:
        ql = q.lower()
        tools = [t for t in tools if ql in t.name.lower() or ql in t.description.lower()]
    return [ToolSummaryOut(name=t.name, description=t.description, tier=t.tier) for t in tools]


@router.get("/{name}", auth=authenticated, response=ToolDetailOut)
def describe_tool(request, name: str):
    """The tool's input schema, permission, and tier (only if the caller is authorized)."""
    tool = registry.get(name)
    if tool is None:
        raise service.ToolError(f"unknown tool {name!r}", 404)
    if tool not in service.accessible(request.auth.id):
        raise service.ToolError(f"missing permission {tool.perm!r}", 403)
    return ToolDetailOut(**service.describe(tool))


@router.post("/{name}/invoke", auth=authenticated)
def invoke_tool(request, name: str):
    """Invoke a tool with a JSON body; perm/tier/validation enforced by the service."""
    body = json.loads(request.body or b"{}")
    return service.invoke(name, body, user_id=request.auth.id)
