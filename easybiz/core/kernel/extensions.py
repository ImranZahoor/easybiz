from __future__ import annotations

from django.db import connection

from easybiz.core.kernel import state
from easybiz.core.kernel.registry import registry

# point name -> [(impl, module_id), ...]; a point fans out to MANY contributors,
# unlike a capability which resolves to ONE provider.
_contributors: dict[str, list[tuple[object, str]]] = {}


def register(point: str, impl: object, module_id: str) -> None:
    """Append a contributor to an extension point (many per point)."""
    _contributors.setdefault(point, []).append((impl, module_id))


def contributors(point: str) -> list:
    """Impls whose module is enabled for the current tenant, in dependency/load order.

    Semantics-free: the host module decides how to combine them (all-pass /
    collect / first-wins / notify).
    """
    tenant = getattr(connection, "tenant", None)
    if tenant is None:
        return []
    entries = [(impl, mid) for impl, mid in _contributors.get(point, []) if state.is_enabled(tenant, mid)]
    order = registry.load_order()
    return [impl for impl, _ in sorted(entries, key=lambda e: order.index(e[1]))]
