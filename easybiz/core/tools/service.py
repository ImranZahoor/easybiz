from __future__ import annotations

from pydantic import ValidationError

from easybiz.core.audit import service as audit
from easybiz.core.errors import DomainError
from easybiz.core.iam import cache as iam_cache
from easybiz.core.iam import service as iam
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool, registry


class ToolError(DomainError):
    """A tool could not be invoked (unknown / forbidden / invalid input)."""


def _allowed(tool: Tool, perms: set[str]) -> bool:
    return tool.perm is None or iam.has_permission(perms, tool.perm)


def accessible(user_id) -> list[Tool]:
    """Tools the caller is authorized to see/use (perm-filtered)."""
    perms = iam_cache.cached_permissions_for(user_id)
    return [t for t in registry.all() if _allowed(t, perms)]


def describe(tool: Tool) -> dict:
    schema = tool.input_schema.model_json_schema() if tool.input_schema is not None else None
    return {
        "name": tool.name,
        "description": tool.description,
        "tier": tool.tier,
        "perm": tool.perm,
        "input_schema": schema,
    }


def invoke(name: str, raw_inputs: dict, *, user_id) -> object:
    """Enforce perm + tier + input validation, run the tool's handler, and audit the call."""
    tool = registry.get(name)
    if tool is None:
        raise ToolError(f"unknown tool {name!r}", 404)
    perms = iam_cache.cached_permissions_for(user_id)
    if not _allowed(tool, perms):
        raise ToolError(f"missing permission {tool.perm!r}", 403)
    if tool.tier is not ToolTier.READ:
        raise ToolError("only read tools are available (write/admin need an agent key)", 403)
    inputs = raw_inputs or {}
    if not isinstance(inputs, dict):
        raise ToolError("input must be a JSON object", 422)
    params = None
    if tool.input_schema is not None:
        extra = set(inputs) - set(tool.input_schema.model_fields)
        if extra:
            raise ToolError(f"unexpected input(s): {sorted(extra)}", 422)
        try:
            params = tool.input_schema(**inputs)
        except ValidationError as exc:
            raise ToolError(f"invalid input: {exc}", 422) from exc
    elif inputs:
        raise ToolError(f"{name!r} takes no input", 422)
    result = tool.handler(user_id, params)
    audit.record(user_id, "tool.invoked", entity="tool", entity_id=name)
    return result
