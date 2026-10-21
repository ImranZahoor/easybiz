"""Module registry: manifests, dependency graph, handlers, discovery wiring."""

from __future__ import annotations

from easybiz.core.kernel.manifest import Manifest, Version, VersionRange


class RegistryError(Exception):
    """Raised for an unsatisfiable or cyclic module dependency graph."""


class Registry:
    """Holds loaded manifests and derives load order, dependents, and handlers."""

    def __init__(self) -> None:
        self._manifests: dict[str, Manifest] = {}
        self._handlers: dict[str, list] = {}
        self._loaded = False

    def add(self, manifest: Manifest) -> None:
        if manifest.id in self._manifests:
            raise RegistryError(f"duplicate module {manifest.id!r}")
        self._manifests[manifest.id] = manifest

    def manifest(self, module_id: str) -> Manifest | None:
        return self._manifests.get(module_id)

    def dependents_of(self, module_id: str) -> list[str]:
        return sorted(
            m.id
            for m in self._manifests.values()
            if module_id in {dep for dep, _ in m.requires}
        )

    def load_order(self) -> list[str]:
        for m in self._manifests.values():
            for dep, rng in m.requires:
                target = self._manifests.get(dep)
                if target is None:
                    raise RegistryError(
                        f"module {dep!r} required by {m.id!r} is not installed"
                    )
                if not VersionRange.parse(rng).contains(Version.parse(target.version)):
                    raise RegistryError(
                        f"module {m.id!r} requires {dep!r} {rng}, found {target.version}"
                    )
        order: list[str] = []
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(mid: str) -> None:
            if mid in done:
                return
            if mid in visiting:
                raise RegistryError(f"dependency cycle involving {mid!r}")
            visiting.add(mid)
            for dep, _ in self._manifests[mid].requires:
                visit(dep)
            visiting.discard(mid)
            done.add(mid)
            order.append(mid)

        for mid in sorted(self._manifests):
            visit(mid)
        return order
