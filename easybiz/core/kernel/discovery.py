from collections.abc import Iterable


def discover_module_packages(explicit: Iterable[str]) -> list[str]:
    """Return the configured module packages.

    The spec (§5.3) also merges packages that register an ``easybiz.modules``
    entry point; that merge is deferred until a packaged module ships one.
    """
    return list(explicit)
