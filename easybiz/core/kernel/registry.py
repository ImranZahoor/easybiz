"""Module registry: manifests, dependency graph, handlers, discovery wiring."""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

from easybiz.core.kernel.manifest import Manifest, Version, VersionRange, parse_manifest


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
            m.id for m in self._manifests.values() if any(dep == module_id for dep, _ in m.requires)
        )

    def load_order(self) -> list[str]:
        """Validate every requirement, then return ids in dependency-first order."""
        self._assert_requirements()
        return self._topological_order()

    def _assert_requirements(self) -> None:
        """Each `requires` target must be installed and satisfy its version range."""
        for m in self._manifests.values():
            for dep, rng in m.requires:
                target = self._manifests.get(dep)
                if target is None:
                    raise RegistryError(f"module {dep!r} required by {m.id!r} is not installed")
                if not VersionRange.parse(rng).contains(Version.parse(target.version)):
                    raise RegistryError(
                        f"module {m.id!r} requires {dep!r} {rng}, found {target.version}"
                    )

    def _topological_order(self) -> list[str]:
        """Depth-first topological sort; raises on a dependency cycle."""
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

    # --- runtime wiring ------------------------------------------------------

    def module_id_for(self, dotted_name: str) -> str | None:
        """Longest-prefix match of a dotted path to a module id.

        Returns ``"core"`` for ``easybiz.core*`` and the module id for a
        registered package; ``None`` when the path matches nothing (so an
        unknown module is never silently trusted as core).
        """
        if dotted_name == "easybiz.core" or dotted_name.startswith("easybiz.core."):
            return "core"
        best_id, best_len = None, -1
        for mid, m in self._manifests.items():
            pkg = m.package
            if pkg and (dotted_name == pkg or dotted_name.startswith(pkg + ".")):
                if len(pkg) > best_len:
                    best_id, best_len = mid, len(pkg)
        return best_id

    def add_handler(self, event: str, func) -> None:
        """Register an event handler; a non-core handler must declare the subscription."""
        module_id = self.module_id_for(func.__module__)
        if module_id is None:
            raise RegistryError(f"handler module {func.__module__!r} maps to no known module")
        if module_id != "core":
            manifest = self._manifests.get(module_id)
            if manifest is None or event not in manifest.subscribes:
                raise RegistryError(
                    f"handler for {event!r} is not declared in {module_id!r} subscribes"
                )
        self._handlers.setdefault(event, []).append(func)

    def subscribe(self, event: str):
        """Decorator form of add_handler, inferring the module from the handler."""

        def decorator(func):
            self.add_handler(event, func)
            return func

        return decorator

    def load_packages(self, packages) -> None:
        """Read and validate each package's manifest.json, then check the graph."""
        for package in packages:
            spec = importlib.util.find_spec(package)
            if spec is None or not spec.submodule_search_locations:
                raise RegistryError(f"module package {package!r} not found")
            location = next(iter(spec.submodule_search_locations))
            try:
                data = json.loads((Path(location) / "manifest.json").read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise RegistryError(f"module {package!r} has no readable manifest.json") from exc
            self.add(parse_manifest(data, package=package))
        self.load_order()

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        from django.conf import settings

        self.load_packages(settings.EASYBIZ_MODULE_PACKAGES)
        self._loaded = True

    def verify_apps(self) -> None:
        """Each module's Django app label must equal its id and name equal its package."""
        from django.apps import apps

        for mid, manifest in self._manifests.items():
            try:
                app = apps.get_app_config(mid)
            except LookupError as exc:
                raise RegistryError(f"module {mid!r} has no Django app with label {mid!r}") from exc
            if app.name != manifest.package:
                raise RegistryError(
                    f"app {mid!r} name {app.name!r} != package {manifest.package!r}"
                )

    def import_module_code(self) -> None:
        """Import each module's handlers/providers, then check declared subscriptions."""
        for manifest in self._manifests.values():
            self._import_optional(f"{manifest.package}.handlers")
            self._import_optional(f"{manifest.package}.providers")
        self._assert_subscriptions_satisfied()

    @staticmethod
    def _import_optional(dotted_name: str) -> None:
        """Import a module if it exists; a missing handlers/providers module is fine."""
        if importlib.util.find_spec(dotted_name) is not None:
            importlib.import_module(dotted_name)

    def _assert_subscriptions_satisfied(self) -> None:
        """Every declared subscription must have had a handler registered on import."""
        for manifest in self._manifests.values():
            for event in manifest.subscribes:
                if not self._handlers.get(event):
                    raise RegistryError(
                        f"module {manifest.id!r} subscribes {event!r} with no handler"
                    )


registry = Registry()


def subscribe(event: str):
    """Module-level decorator registering a handler on the default registry."""
    return registry.subscribe(event)
