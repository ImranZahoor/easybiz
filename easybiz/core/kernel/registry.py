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
            m.id for m in self._manifests.values() if module_id in {dep for dep, _ in m.requires}
        )

    def load_order(self) -> list[str]:
        for m in self._manifests.values():
            for dep, rng in m.requires:
                target = self._manifests.get(dep)
                if target is None:
                    raise RegistryError(f"module {dep!r} required by {m.id!r} is not installed")
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

    # --- runtime wiring ------------------------------------------------------

    def module_id_for(self, dotted_name: str) -> str:
        """Longest-prefix match of a dotted module path to a module id (`core` default)."""
        if dotted_name == "easybiz.core" or dotted_name.startswith("easybiz.core."):
            return "core"
        best_id, best_len = "core", -1
        for mid, m in self._manifests.items():
            pkg = m.package
            if pkg and (dotted_name == pkg or dotted_name.startswith(pkg + ".")):
                if len(pkg) > best_len:
                    best_id, best_len = mid, len(pkg)
        return best_id

    def add_handler(self, event: str, func) -> None:
        """Register an event handler; a non-core handler must declare the subscription."""
        module_id = self.module_id_for(func.__module__)
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
            data = json.loads((Path(location) / "manifest.json").read_text())
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
            app = apps.get_app_config(mid)
            if app.name != manifest.package:
                raise RegistryError(
                    f"app {mid!r} name {app.name!r} != package {manifest.package!r}"
                )

    def import_module_code(self) -> None:
        """Import each module's handlers/providers, then check declared subscriptions."""
        for manifest in self._manifests.values():
            for suffix in ("handlers", "providers"):
                name = f"{manifest.package}.{suffix}"
                if importlib.util.find_spec(name) is not None:
                    importlib.import_module(name)
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
