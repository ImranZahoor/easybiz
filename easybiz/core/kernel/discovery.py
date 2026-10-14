from collections.abc import Iterable


def discover_module_packages(explicit: Iterable[str]) -> list[str]:
    """Return configured module packages; entry-point merge is added in M2."""
    return list(explicit)
