from __future__ import annotations

from dataclasses import dataclass

from django.db import connection
from pydantic import ValidationError

from easybiz.core.audit import service as audit
from easybiz.core.errors import DomainError
from easybiz.core.iam import cache as iam_cache
from easybiz.core.iam import service as iam
from easybiz.core.kernel import state
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool, registry


class ToolError(DomainError):
    """A tool could not be invoked (unknown / unavailable / forbidden / invalid input)."""


@dataclass
class Principal:
    """Who is invoking a tool: a user (chatbot/JWT) or an agent key acting on behalf of one."""

    subject_user_id: object  # the user whose RBAC+ABAC authority is used
    scope: str  # "read" | "write"
    allowlist: set[str] | None  # None = all tools; set = only these (agent key)
    actor_id: object  # audit actor (the user, or the agent key id)
    on_behalf_of: object | None  # the user an agent key acts for (else None)
    key_perms: set[str] | None  # an agent key's permission subset (None = user, no key cap)

    @classmethod
    def from_user(cls, user_id) -> Principal:
        return cls(
            subject_user_id=user_id,
            scope="write",
            allowlist=None,
            actor_id=user_id,
            on_behalf_of=None,
            key_perms=None,
        )

    @classmethod
    def from_agent_key(cls, key) -> Principal:
        return cls(
            subject_user_id=key.on_behalf_of_user,
            scope=key.scope,
            allowlist=set(key.tool_allowlist or []),
            actor_id=key.id,
            on_behalf_of=key.on_behalf_of_user,
            key_perms=set(key.permissions),
        )

    def key_allows(self, perm: str | None) -> bool:
        """The agent key's own permission subset (a user has no key cap)."""
        return self.key_perms is None or perm is None or iam.has_permission(self.key_perms, perm)


def _enabled(tool: Tool) -> bool:
    """A core tool is always available; a module tool only while its module is enabled here."""
    if tool.module_id is None:
        return True
    tenant = getattr(connection, "tenant", None)
    return tenant is not None and state.is_enabled(tenant, tool.module_id)


def _tier_ok(tool: Tool, principal: Principal) -> bool:
    if tool.tier is ToolTier.ADMIN:
        return False  # admin/irreversible tools are never agent-invocable in this slice
    if tool.tier is ToolTier.WRITE and principal.scope != "write":
        return False
    return True


def _visible(tool: Tool, principal: Principal, perms: set[str]) -> bool:
    """Discovery filter: enabled, in allowlist, tier≤scope, key-subset, and the user holds the perm."""
    if not _enabled(tool):
        return False
    if principal.allowlist is not None and tool.name not in principal.allowlist:
        return False
    if not _tier_ok(tool, principal):
        return False
    if not principal.key_allows(tool.perm):
        return False
    return tool.perm is None or iam.has_permission(perms, tool.perm)


def accessible_for(principal: Principal) -> list[Tool]:
    perms = iam_cache.cached_permissions_for(principal.subject_user_id)
    return [t for t in registry.all() if _visible(t, principal, perms)]


def accessible(user_id) -> list[Tool]:
    return accessible_for(Principal.from_user(user_id))


def describe(tool: Tool) -> dict:
    schema = tool.input_schema.model_json_schema() if tool.input_schema is not None else None
    return {
        "name": tool.name,
        "description": tool.description,
        "tier": tool.tier,
        "perm": tool.perm,
        "input_schema": schema,
    }


def _invoke(name: str, raw_inputs: dict, principal: Principal) -> object:
    """Gate (allowlist → tier/scope → key-subset → authorize) then run + audit."""
    tool = registry.get(name)
    if tool is None:
        raise ToolError(f"unknown tool {name!r}", 404)
    if not _enabled(tool):
        raise ToolError(f"tool {name!r} is not available", 404)  # module disabled → gate 404
    if principal.allowlist is not None and name not in principal.allowlist:
        raise ToolError(f"tool {name!r} is not in this key's allowlist", 403)
    if tool.tier is ToolTier.ADMIN:
        raise ToolError("admin tools are not available to agents", 403)
    if tool.tier is ToolTier.WRITE and principal.scope != "write":
        raise ToolError("this credential has read-only scope", 403)
    if not principal.key_allows(tool.perm):
        raise ToolError(f"{tool.perm!r} is outside this key's scope", 403)
    if tool.perm is not None and not iam.authorize(principal.subject_user_id, tool.perm):
        raise ToolError(f"missing permission {tool.perm!r}", 403)
    params = _validate(tool, raw_inputs)
    result = tool.handler(principal.subject_user_id, params)
    after = {"on_behalf_of": str(principal.on_behalf_of)} if principal.on_behalf_of else None
    audit.record(principal.actor_id, "tool.invoked", entity="tool", entity_id=name, after=after)
    return result


def _validate(tool: Tool, raw_inputs):
    inputs = raw_inputs or {}
    if not isinstance(inputs, dict):
        raise ToolError("input must be a JSON object", 422)
    if tool.input_schema is None:
        if inputs:
            raise ToolError(f"{tool.name!r} takes no input", 422)
        return None
    extra = set(inputs) - set(tool.input_schema.model_fields)
    if extra:
        raise ToolError(f"unexpected input(s): {sorted(extra)}", 422)
    try:
        return tool.input_schema(**inputs)
    except ValidationError as exc:
        raise ToolError(f"invalid input: {exc}", 422) from exc


def invoke(name: str, raw_inputs: dict, *, user_id) -> object:
    """User-principal convenience over ``_invoke`` (JWT/chatbot path)."""
    return _invoke(name, raw_inputs, Principal.from_user(user_id))
