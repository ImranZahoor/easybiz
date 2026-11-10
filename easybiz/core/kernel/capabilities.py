from __future__ import annotations

import logging

from django.db import connection

from easybiz.core.kernel import state
from easybiz.core.kernel.manifest import Version, VersionRange

logger = logging.getLogger("easybiz.capabilities")


class CapabilityUnavailable(Exception):
    """Raised when a requested capability's provider module is not enabled or incompatible."""


_providers: dict[type, tuple[object, str, str]] = {}  # contract -> (impl, module_id, version)


def register(contract: type, impl: object, module_id: str, version: str = "1.0.0") -> None:
    _providers[contract] = (impl, module_id, version)


def provider_meta(contract: type) -> tuple[str, str] | None:
    """The registered ``(module_id, version)`` for a contract, or None if unregistered."""
    entry = _providers.get(contract)
    return (entry[1], entry[2]) if entry is not None else None


def get(contract: type, range: str | None = None, optional: bool = False):
    """The enabled, version-compatible provider for a contract (or None/raise)."""
    entry = _providers.get(contract)
    if entry is not None:
        impl, module_id, version = entry
        tenant = getattr(connection, "tenant", None)
        enabled = tenant is not None and state.is_enabled(tenant, module_id)
        if enabled and _compatible(contract, version, range):
            return impl
    if optional:
        return None
    name = getattr(contract, "__name__", contract)
    raise CapabilityUnavailable(f"no enabled, compatible provider for {name!r}")


def _compatible(contract: type, version: str, range: str | None) -> bool:
    """True if ``version`` satisfies ``range`` (None = any); logs and returns False otherwise."""
    if range is None:
        return True
    if VersionRange.parse(range).contains(Version.parse(version)):
        return True
    name = getattr(contract, "__name__", contract)
    logger.warning("provider for %r is version %s, incompatible with range %s", name, version, range)
    return False
