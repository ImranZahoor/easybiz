"""Capability registry: resolve a contract only while its provider is enabled."""

from __future__ import annotations

from django.db import connection

from easybiz.core.kernel import state


class CapabilityUnavailable(Exception):
    """Raised when a requested capability's provider module is not enabled."""


_providers: dict[type, tuple[object, str]] = {}


def register(contract: type, impl: object, module_id: str) -> None:
    _providers[contract] = (impl, module_id)


def get(contract: type, optional: bool = False):
    entry = _providers.get(contract)
    if entry is not None:
        impl, module_id = entry
        tenant = getattr(connection, "tenant", None)
        if tenant is not None and state.is_enabled(tenant, module_id):
            return impl
    if optional:
        return None
    name = getattr(contract, "__name__", contract)
    raise CapabilityUnavailable(f"no enabled provider for {name!r}")
