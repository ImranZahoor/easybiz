from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from easybiz.core.tools.enums import ToolTier


@dataclass(frozen=True)
class Tool:
    """A transport-agnostic wrapper over an existing query/command (no business logic here)."""

    name: str
    description: str
    tier: ToolTier
    perm: str | None
    idempotent: bool
    input_schema: type | None
    handler: Callable[[object, object], object]  # (user_id, validated_params) -> result


class ToolRegistry:
    """Holds the registered agent tools, keyed by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def search(self, query: str) -> list[Tool]:
        q = (query or "").lower()
        return [t for t in self._tools.values() if q in t.name.lower() or q in t.description.lower()]


registry = ToolRegistry()
