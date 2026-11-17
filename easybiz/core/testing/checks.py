from __future__ import annotations

import ast
import importlib
import importlib.util
import os
from pathlib import Path

from django.apps import apps

from easybiz.core.kernel.manifest import Manifest
from easybiz.core.kernel.registry import registry

# --- static checks -----------------------------------------------------------


def check_manifest_and_app_label(module_id: str) -> list[str]:
    """The module's manifest loads and its Django app label/name match (app label == id)."""
    manifest = registry.manifest(module_id)
    if manifest is None:
        return [f"{module_id}: no loaded manifest"]
    try:
        app = apps.get_app_config(module_id)
    except LookupError:
        return [f"{module_id}: no Django app with label {module_id!r}"]
    out = []
    if app.label != module_id:
        out.append(f"{module_id}: app label {app.label!r} != {module_id!r}")
    if app.name != manifest.package:
        out.append(f"{module_id}: app name {app.name!r} != package {manifest.package!r}")
    return out


def _module_router(module_id: str):
    dotted = f"easybiz.modules.{module_id}.api"
    if importlib.util.find_spec(dotted) is None:
        return None
    return getattr(importlib.import_module(dotted), "router", None)


def _undeclared_endpoint_perms(perms_used: set[str], declared: set[str]) -> set[str]:
    """Permission codes used by endpoints that are neither core (`core.*`) nor declared."""
    return {p for p in perms_used if not p.startswith("core.") and p not in declared}


def check_endpoint_permissions(module_id: str) -> list[str]:
    """Every permission an endpoint guards on is declared by the module (or is a core permission)."""
    router = _module_router(module_id)
    if router is None:
        return []
    perms_used: set[str] = set()
    for path_view in router.path_operations.values():
        for op in path_view.operations:
            for auth in getattr(op, "auth_callbacks", None) or []:
                code = getattr(auth, "permission", None)
                if code:
                    perms_used.add(code)
    manifest = registry.manifest(module_id)
    declared = {code for code, _ in manifest.permissions} if manifest else set()
    bad = _undeclared_endpoint_perms(perms_used, declared)
    return [f"{module_id}: endpoint uses undeclared permission {p!r}" for p in sorted(bad)]


def _missing_handlers(manifest: Manifest) -> list[str]:
    return [e for e in manifest.subscribes if not registry.handlers_for(e)]


def check_events(module_id: str) -> list[str]:
    """Every subscribed event has a registered handler (publish declaration is enforced elsewhere)."""
    manifest = registry.manifest(module_id)
    if manifest is None:
        return [f"{module_id}: no loaded manifest"]
    return [f"{module_id}: subscription {e!r} has no handler" for e in _missing_handlers(manifest)]


def _scan_imports(package_dir: str, self_id: str) -> list[str]:
    """Dotted imports of other modules (`easybiz.modules.<other>`) found under a package dir."""
    offenders: list[str] = []
    for root, _dirs, files in os.walk(package_dir):
        for name in files:
            if not name.endswith(".py"):
                continue
            tree = ast.parse(Path(root, name).read_text())
            for node in ast.walk(tree):
                mods: list[str] = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                for mod in mods:
                    if mod.startswith("easybiz.modules.") and mod.split(".")[2] != self_id:
                        offenders.append(mod)
    return offenders


def check_no_cross_imports(module_id: str) -> list[str]:
    """The module imports no other module's package (self and easybiz.core are allowed)."""
    manifest = registry.manifest(module_id)
    spec = importlib.util.find_spec(manifest.package) if manifest and manifest.package else None
    if spec is None or not spec.submodule_search_locations:
        return [f"{module_id}: package not importable"]
    location = next(iter(spec.submodule_search_locations))
    return [f"{module_id}: imports another module {m!r}" for m in _scan_imports(location, module_id)]


def _relation_offenders(model: type, module_id: str) -> list[str]:
    """Concrete relation fields on ``model`` whose target lives in another app."""
    offenders: list[str] = []
    for field in model._meta.get_fields():
        if not (field.is_relation and getattr(field, "concrete", False)):
            continue
        related = field.related_model
        if related is not None and related._meta.app_label != module_id:
            offenders.append(f"{field.name} -> {related._meta.app_label}")
    return offenders


def check_no_cross_fk_and_prefix(module_id: str) -> list[str]:
    """Every model table carries the `<id>_` prefix and has no FK to another module."""
    out: list[str] = []
    for model in apps.get_app_config(module_id).get_models():
        if not model._meta.db_table.startswith(f"{module_id}_"):
            out.append(f"{module_id}: table {model._meta.db_table!r} lacks prefix {module_id}_")
        for offender in _relation_offenders(model, module_id):
            out.append(f"{module_id}: {model.__name__} has a cross-module relation {offender}")
    return out
