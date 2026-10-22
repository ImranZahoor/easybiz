# Easybiz M2 (Kernel Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the no-DB kernel — manifest parsing/validation, version ranges, the module registry (dependency graph, load order, handlers), discovery, contracts — and wire registry loading into Django startup, so `tests/test_manifest_and_registry.py` (26 tests) passes.

**Architecture:** Pure-Python kernel with no database dependency. `manifest.py` parses+validates a manifest dict and implements version/version-range semantics. `registry.py` holds manifests, computes dependency load order, detects missing/incompatible/cyclic deps, maps dotted module paths to ids, and registers event handlers. `discovery.py` merges the settings module list with `easybiz.modules` entry points. `contracts.py` declares capability Protocols. `kernel/apps.py::ready()` loads+validates the real modules at startup.

**Tech Stack:** Python 3.13, Django 6.1 (AppConfig.ready, importlib, entry points), pytest; `uv`. No PostgreSQL needed for M2's tests.

**Spec:** `ERP-CORE-SPEC.md` — manifest (§5.1), registry (§5.2), discovery (§5.3), capabilities/contracts (§5.8), test catalogue (§10 `test_manifest_and_registry.py`), M2 (§11), invariant I8 (permission/event prefixes), naming (§0.4).

## Scope decision (please note)

§11 lists `state.py` and `capabilities.py` under M2, but both depend on `catalog_tenantmodule` and tenant/connection context, which arrive in **M3**. M2's only verification is the 26 no-DB manifest/registry tests. **Ruling:** M2 builds `manifest.py`, `registry.py`, `discovery.py`, `contracts.py`, and the `apps.py` startup wiring. `state.py` and `capabilities.py` are **deferred to M3**, where the catalog models and their tests (lifecycle, capability-while-enabled) live. `contracts.py` (pure `typing.Protocol` definitions) is built now so the contract surface exists; nothing imports it until a module provides/consumes it (M6).

## Global Constraints

- Python 3.13 (floor 3.12); Django ≥5.2 (running 6.1); `uv` only; `pytest` (pytest-django off).
- Namespace `easybiz.core.*` / `easybiz.modules.*`. Core module id resolves to `"core"`.
- Manifest `id`: `^[a-z][a-z0-9_]{1,30}$` (2–31 chars), not in `{core, auth, platform, admin, docs, openapi}`, must equal the Django app label (startup check). `version`: `^\d+(\.\d+){0,2}$`, zero-padded.
- Version ranges: exact `1.2.3`; caret `^1.2`→`>=1.2.0 <2.0.0`, `^0.2.1`→`>=0.2.1 <0.3.0`, `^0.0.3`→`>=0.0.3 <0.0.4`; tilde `~1.2.3`→`>=1.2.3 <1.3.0`; `>=1.2`; `*`. `range` defaults to `*`.
- I8: permission codes and published events must start with `<id>.`; role permissions ⊆ declared permissions; `optional` may not repeat a `requires` entry; a module may not depend on itself.
- §0.5: short imperative commits, no attribution; docstrings on public classes/functions; types in `types.py` where UI/schema types arise (kernel uses plain dataclasses here); `ruff` + `mypy easybiz config` stay clean.
- `RegistryError` messages contain `"not installed"`, the version found, or `"cycle"` (per §5.2).

## Review Focus

Each pinned to the task that owns it.

- **Caret 0.x edge cases** (`^0.2.1`→`<0.3.0`, `^0.0.3`→`<0.0.4`) and **version zero-padding** (`1` vs `1.0.0`) are the easiest range bugs. → Task 1.
- **`id` regex boundaries** (reject 1-char `a`, accept 2-char `hr`; reject 32+ chars) and **reserved ids**. → Task 2.
- **`optional` repeating a `requires` entry, self-dependency, duplicate dependency** must all be rejected at parse. → Task 2.
- **Cycle detection** must fire for mutual deps (ids ≥2 chars), and **missing vs incompatible** dependency errors must carry the right message (`not installed` vs the found version). → Task 3.
- **Startup wiring must not break the gate** — `ready()` loading the real timesheets manifest must leave `manage.py check` and the suite green, and skip absent `handlers`/`providers`. → Task 4.

---

### Task 1: Versions and version ranges

**Files:**
- Create: `easybiz/core/kernel/manifest.py` (version pieces only this task)
- Test: `tests/test_manifest_and_registry.py` (version-range cases)

**Interfaces:**
- Consumes: nothing.
- Produces: `Version.parse(str) -> Version` (orderable, zero-padded to 3 parts); `VersionRange.parse(str) -> VersionRange` with `contains(Version) -> bool`; `ManifestError`.

- [ ] **Step 1: Write failing tests (version truth table)**

```python
# tests/test_manifest_and_registry.py
import pytest

from easybiz.core.kernel.manifest import ManifestError, Version, VersionRange


def _in(range_str, version_str):
    return VersionRange.parse(range_str).contains(Version.parse(version_str))


def test_exact_range():
    assert _in("1.2.3", "1.2.3")
    assert not _in("1.2.3", "1.2.4")


def test_padding_treats_1_as_1_0_0():
    assert Version.parse("1") == Version.parse("1.0.0")
    assert _in("1", "1.0.0")


def test_caret_major():
    assert _in("^1.2", "1.2.0") and _in("^1.2", "1.9.9")
    assert not _in("^1.2", "2.0.0")
    assert not _in("^1.2", "1.1.0")


def test_caret_zero_minor():
    assert _in("^0.2.1", "0.2.1") and _in("^0.2.1", "0.2.9")
    assert not _in("^0.2.1", "0.3.0")


def test_caret_zero_zero_patch():
    assert _in("^0.0.3", "0.0.3")
    assert not _in("^0.0.3", "0.0.4")


def test_tilde():
    assert _in("~1.2.3", "1.2.3") and _in("~1.2.3", "1.2.9")
    assert not _in("~1.2.3", "1.3.0")


def test_gte_and_wildcard():
    assert _in(">=1.2", "1.2.0") and _in(">=1.2", "9.9.9")
    assert not _in(">=1.2", "1.1.9")
    assert _in("*", "0.0.1") and _in("*", "99.0.0")


def test_invalid_version_rejected():
    with pytest.raises(ManifestError):
        Version.parse("1.2.3.4")
    with pytest.raises(ManifestError):
        Version.parse("x")
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_manifest_and_registry.py -v`
Expected: FAIL — `manifest` module/classes undefined.

- [ ] **Step 3: Implement versions in `manifest.py`**

```python
"""Module manifest parsing, validation, and version-range semantics."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_VERSION_RE = re.compile(r"^\d+(\.\d+){0,2}$")


class ManifestError(Exception):
    """Raised when a manifest or version/range is invalid."""


@dataclass(frozen=True, order=True)
class Version:
    parts: tuple[int, int, int]

    @classmethod
    def parse(cls, raw: str) -> Version:
        if not isinstance(raw, str) or not _VERSION_RE.match(raw):
            raise ManifestError(f"invalid version: {raw!r}")
        nums = [int(p) for p in raw.split(".")]
        nums += [0] * (3 - len(nums))
        return cls((nums[0], nums[1], nums[2]))


@dataclass(frozen=True)
class VersionRange:
    """A parsed version constraint with an inclusive lower and exclusive upper bound."""

    low: Version | None
    high: Version | None  # exclusive

    def contains(self, v: Version) -> bool:
        if self.low is not None and v < self.low:
            return False
        if self.high is not None and v >= self.high:
            return False
        return True

    @classmethod
    def parse(cls, raw: str) -> VersionRange:
        raw = (raw or "*").strip()
        if raw == "*":
            return cls(None, None)
        if raw.startswith(">="):
            return cls(Version.parse(raw[2:]), None)
        if raw.startswith("^"):
            return cls._caret(raw[1:])
        if raw.startswith("~"):
            return cls._tilde(raw[1:])
        exact = Version.parse(raw)
        hi = Version((exact.parts[0], exact.parts[1], exact.parts[2] + 1))
        return cls(exact, hi)

    @classmethod
    def _caret(cls, base: str) -> VersionRange:
        low = Version.parse(base)
        major, minor, patch = low.parts
        if major > 0:
            high = Version((major + 1, 0, 0))
        elif minor > 0:
            high = Version((0, minor + 1, 0))
        else:
            high = Version((0, 0, patch + 1))
        return cls(low, high)

    @classmethod
    def _tilde(cls, base: str) -> VersionRange:
        low = Version.parse(base)
        major, minor, _ = low.parts
        return cls(low, Version((major, minor + 1, 0)))
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_manifest_and_registry.py -v`
Expected: PASS (all version tests).

- [ ] **Step 5: Commit**

```bash
git add easybiz/core/kernel/manifest.py tests/test_manifest_and_registry.py
git commit -m "Add version parsing and range semantics"
```

---

### Task 2: Manifest parsing and validation

**Files:**
- Modify: `easybiz/core/kernel/manifest.py`
- Test: `tests/test_manifest_and_registry.py` (manifest cases)

**Interfaces:**
- Consumes: `Version`/`VersionRange`/`ManifestError` from Task 1.
- Produces: `Manifest` dataclass and `parse_manifest(data: dict, *, package: str | None = None) -> Manifest`. Fields: `id, name, version, requires: list[Dep], optional: list[Dep], provides, consumes, permissions: list[tuple[str,str]], roles, publishes, subscribes, menu, package`. `Dep = tuple[str, str]` (module, range). Raises `ManifestError` on any rule violation.

- [ ] **Step 1: Write failing tests**

```python
RESERVED = {"core", "auth", "platform", "admin", "docs", "openapi"}


def _m(**over):
    base = {"id": "hr", "version": "1.0.0"}
    base.update(over)
    return base


def test_minimal_manifest_defaults_name_to_id():
    from easybiz.core.kernel.manifest import parse_manifest

    m = parse_manifest(_m())
    assert m.id == "hr" and m.name == "hr" and m.version == "1.0.0"


def test_missing_id_rejected():
    from easybiz.core.kernel.manifest import parse_manifest
    with pytest.raises(ManifestError):
        parse_manifest({"version": "1.0.0"})


@pytest.mark.parametrize("bad", ["A", "1hr", "a", "x" * 32, "hr-x"])
def test_bad_id_rejected(bad):
    from easybiz.core.kernel.manifest import parse_manifest
    with pytest.raises(ManifestError):
        parse_manifest(_m(id=bad))


@pytest.mark.parametrize("rid", sorted(RESERVED))
def test_reserved_id_rejected(rid):
    from easybiz.core.kernel.manifest import parse_manifest
    with pytest.raises(ManifestError):
        parse_manifest(_m(id=rid))


def test_bad_version_rejected():
    from easybiz.core.kernel.manifest import parse_manifest
    with pytest.raises(ManifestError):
        parse_manifest(_m(version="1.2.3.4"))


def test_permission_prefix_enforced():
    from easybiz.core.kernel.manifest import parse_manifest
    with pytest.raises(ManifestError):
        parse_manifest(_m(permissions=[{"code": "other.read", "description": "x"}]))


def test_event_prefix_enforced():
    from easybiz.core.kernel.manifest import parse_manifest
    with pytest.raises(ManifestError):
        parse_manifest(_m(events={"publishes": ["other.thing.done"], "subscribes": []}))


def test_role_permission_must_be_declared():
    from easybiz.core.kernel.manifest import parse_manifest
    with pytest.raises(ManifestError):
        parse_manifest(
            _m(
                permissions=[{"code": "hr.read", "description": "x"}],
                roles=[{"name": "r", "description": "d", "permissions": ["hr.write"]}],
            )
        )


def test_self_dependency_rejected():
    from easybiz.core.kernel.manifest import parse_manifest
    with pytest.raises(ManifestError):
        parse_manifest(_m(requires=[{"module": "hr", "range": "*"}]))


def test_duplicate_dependency_rejected():
    from easybiz.core.kernel.manifest import parse_manifest
    with pytest.raises(ManifestError):
        parse_manifest(
            _m(requires=[{"module": "a1", "range": "*"}, {"module": "a1", "range": "^1"}])
        )


def test_optional_may_not_repeat_requires():
    from easybiz.core.kernel.manifest import parse_manifest
    with pytest.raises(ManifestError):
        parse_manifest(
            _m(requires=[{"module": "a1"}], optional=[{"module": "a1"}])
        )


def test_requires_range_defaults_to_wildcard():
    from easybiz.core.kernel.manifest import parse_manifest
    m = parse_manifest(_m(requires=[{"module": "a1"}]))
    assert m.requires == [("a1", "*")]
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_manifest_and_registry.py -k "manifest or id or prefix or dependency or requires or role or version" -v`
Expected: FAIL — `parse_manifest`/`Manifest` undefined.

- [ ] **Step 3: Implement `Manifest` + `parse_manifest`**

```python
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_RESERVED_IDS = {"core", "auth", "platform", "admin", "docs", "openapi"}

Dep = tuple[str, str]


@dataclass(frozen=True)
class Manifest:
    id: str
    version: str
    name: str
    requires: list[Dep] = field(default_factory=list)
    optional: list[Dep] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    permissions: list[tuple[str, str]] = field(default_factory=list)
    roles: list[dict] = field(default_factory=list)
    publishes: list[str] = field(default_factory=list)
    subscribes: list[str] = field(default_factory=list)
    menu: list[dict] = field(default_factory=list)
    package: str | None = None


def _deps(raw: object, kind: str) -> list[Dep]:
    out: list[Dep] = []
    for entry in raw or []:
        module = entry.get("module")
        if not module:
            raise ManifestError(f"{kind} entry missing 'module'")
        rng = entry.get("range", "*")
        VersionRange.parse(rng)  # validate the range now
        out.append((module, rng))
    return out


def parse_manifest(data: dict, *, package: str | None = None) -> Manifest:
    """Validate a manifest dict and return a Manifest, or raise ManifestError."""
    mid = data.get("id")
    if not mid or not _ID_RE.match(mid):
        raise ManifestError(f"invalid module id: {mid!r}")
    if mid in _RESERVED_IDS:
        raise ManifestError(f"reserved module id: {mid!r}")
    version = data.get("version")
    if not version or not _VERSION_RE.match(version):
        raise ManifestError(f"invalid version: {version!r}")

    requires = _deps(data.get("requires"), "requires")
    optional = _deps(data.get("optional"), "optional")

    req_ids = [m for m, _ in requires]
    opt_ids = [m for m, _ in optional]
    if mid in req_ids or mid in opt_ids:
        raise ManifestError(f"module {mid!r} cannot depend on itself")
    if len(req_ids) != len(set(req_ids)):
        raise ManifestError("duplicate requires entry")
    if len(opt_ids) != len(set(opt_ids)):
        raise ManifestError("duplicate optional entry")
    if set(req_ids) & set(opt_ids):
        raise ManifestError("optional may not repeat a requires entry")

    permissions = [(p["code"], p.get("description", "")) for p in data.get("permissions", [])]
    for code, _ in permissions:
        if not code.startswith(f"{mid}."):
            raise ManifestError(f"permission {code!r} must start with {mid!r}.")
    declared = {code for code, _ in permissions}

    roles = data.get("roles", [])
    for role in roles:
        for perm in role.get("permissions", []):
            if perm not in declared:
                raise ManifestError(
                    f"role {role.get('name')!r} uses undeclared permission {perm!r}"
                )

    events = data.get("events", {}) or {}
    publishes = list(events.get("publishes", []))
    for name in publishes:
        if not name.startswith(f"{mid}."):
            raise ManifestError(f"event {name!r} must start with {mid!r}.")
    subscribes = list(events.get("subscribes", []))

    return Manifest(
        id=mid,
        version=version,
        name=data.get("name") or mid,
        requires=requires,
        optional=optional,
        provides=list(data.get("provides", [])),
        consumes=list(data.get("consumes", [])),
        permissions=permissions,
        roles=roles,
        publishes=publishes,
        subscribes=subscribes,
        menu=data.get("menu", []),
        package=package,
    )
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_manifest_and_registry.py -v`
Expected: PASS (version + manifest tests).

- [ ] **Step 5: Commit**

```bash
git add easybiz/core/kernel/manifest.py tests/test_manifest_and_registry.py
git commit -m "Add manifest parsing and validation"
```

---

### Task 3: Registry — load order, dependency graph, dependents

**Files:**
- Modify: `easybiz/core/kernel/registry.py` (replace the M0 stub)
- Test: `tests/test_manifest_and_registry.py` (graph cases)

**Interfaces:**
- Consumes: `Manifest`, `VersionRange`, `Version`, `ManifestError` from manifest.py.
- Produces: `RegistryError`; `Registry` with `add(Manifest)`, `load_order() -> list[str]`, `dependents_of(module_id) -> list[str]`. (Runtime helpers — `module_id_for`, handlers, `load_packages`, `ensure_loaded`, `verify_apps`, `import_module_code` — land in Task 4.)

- [ ] **Step 1: Write failing tests**

```python
from easybiz.core.kernel.manifest import parse_manifest
from easybiz.core.kernel.registry import Registry, RegistryError


def _reg(*manifests):
    reg = Registry()
    for data in manifests:
        reg.add(parse_manifest(data))
    return reg


def test_load_order_dependencies_first():
    reg = _reg(
        {"id": "payroll", "version": "1.0.0", "requires": [{"module": "hr", "range": "^1"}]},
        {"id": "hr", "version": "1.2.0"},
    )
    order = reg.load_order()
    assert order.index("hr") < order.index("payroll")


def test_missing_hard_dependency_fails_fast():
    reg = _reg({"id": "payroll", "version": "1.0.0", "requires": [{"module": "hr"}]})
    with pytest.raises(RegistryError, match="not installed"):
        reg.load_order()


def test_incompatible_dependency_version_fails():
    reg = _reg(
        {"id": "payroll", "version": "1.0.0", "requires": [{"module": "hr", "range": "^2"}]},
        {"id": "hr", "version": "1.2.0"},
    )
    with pytest.raises(RegistryError, match="1.2.0"):
        reg.load_order()


def test_dependency_cycle_detected():
    reg = _reg(
        {"id": "aa", "version": "1.0.0", "requires": [{"module": "bb"}]},
        {"id": "bb", "version": "1.0.0", "requires": [{"module": "aa"}]},
    )
    with pytest.raises(RegistryError, match="cycle"):
        reg.load_order()


def test_dependents_of():
    reg = _reg(
        {"id": "hr", "version": "1.0.0"},
        {"id": "payroll", "version": "1.0.0", "requires": [{"module": "hr"}]},
        {"id": "timesheets", "version": "1.0.0", "optional": [{"module": "hr"}]},
    )
    assert reg.dependents_of("hr") == ["payroll"]  # requires only, not optional
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_manifest_and_registry.py -k "load_order or dependency or cycle or dependents" -v`
Expected: FAIL — `Registry`/`RegistryError` not defined (M0 stub has neither).

- [ ] **Step 3: Implement the graph core in `registry.py`**

```python
"""Module registry: manifests, dependency graph, handlers, discovery wiring."""
from __future__ import annotations

from easybiz.core.kernel.manifest import Manifest, Version, VersionRange


class RegistryError(Exception):
    """Raised for an unsatisfiable or cyclic module dependency graph."""


class Registry:
    """Holds loaded manifests and derives load order and dependents."""

    def __init__(self) -> None:
        self._manifests: dict[str, Manifest] = {}

    def add(self, manifest: Manifest) -> None:
        if manifest.id in self._manifests:
            raise RegistryError(f"duplicate module {manifest.id!r}")
        self._manifests[manifest.id] = manifest

    def manifest(self, module_id: str) -> Manifest | None:
        return self._manifests.get(module_id)

    def dependents_of(self, module_id: str) -> list[str]:
        return sorted(
            m.id for m in self._manifests.values()
            if module_id in {dep for dep, _ in m.requires}
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
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_manifest_and_registry.py -v`
Expected: PASS (all version + manifest + graph tests).

- [ ] **Step 5: Commit**

```bash
git add easybiz/core/kernel/registry.py tests/test_manifest_and_registry.py
git commit -m "Add module registry load order and dependency graph"
```

---

### Task 4: Discovery, contracts, runtime helpers, and startup wiring

**Files:**
- Modify: `easybiz/core/kernel/registry.py` (module-id mapping, handlers, package loading, ensure_loaded, verify_apps, import_module_code, singleton + `subscribe`)
- Modify: `easybiz/core/kernel/discovery.py` (merge `easybiz.modules` entry points)
- Create: `easybiz/core/kernel/contracts.py`
- Modify: `easybiz/core/kernel/apps.py` (wire `ready()`)
- Test: `tests/test_manifest_and_registry.py` (module_id_for, add_handler, discovery)

**Interfaces:**
- Consumes: `Registry` from Task 3; `discover_module_packages` (M0 stub); the timesheets package + manifest.
- Produces: `registry` singleton; `subscribe(event)` decorator; `Registry.module_id_for(dotted)`, `Registry.add_handler(event, func)`, `Registry.load_packages(packages)`, `Registry.ensure_loaded()`, `Registry.verify_apps()`, `Registry.import_module_code()`; `contracts.AttendanceProvider`.

- [ ] **Step 1: Write failing tests**

```python
def test_module_id_for_core_prefix():
    reg = Registry()
    assert reg.module_id_for("easybiz.core.kernel.apps") == "core"


def test_module_id_for_longest_module_prefix():
    reg = Registry()
    reg.add(parse_manifest({"id": "timesheets", "version": "0.1.0"}, package="easybiz.modules.timesheets"))
    assert reg.module_id_for("easybiz.modules.timesheets.handlers") == "timesheets"


def test_add_handler_rejects_undeclared_subscription():
    reg = Registry()
    reg.add(parse_manifest({"id": "timesheets", "version": "0.1.0"}, package="easybiz.modules.timesheets"))

    def handler(event):  # module inferred from __module__ at runtime
        return None

    handler.__module__ = "easybiz.modules.timesheets.handlers"
    with pytest.raises(RegistryError, match="not declared"):
        reg.add_handler("timesheets.entry.approved", handler)


def test_discovery_returns_explicit_packages():
    from easybiz.core.kernel.discovery import discover_module_packages

    assert discover_module_packages(["easybiz.modules.timesheets"]) == [
        "easybiz.modules.timesheets"
    ]
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_manifest_and_registry.py -k "module_id_for or add_handler or discovery" -v`
Expected: FAIL — these `Registry` methods not yet defined.

- [ ] **Step 3: Add runtime helpers to `registry.py`**

Append to the `Registry` class and module:

```python
    # --- runtime wiring (added in M2 Task 4) ---------------------------------
    def __init__(self) -> None:  # replace the Task 3 __init__
        self._manifests: dict[str, Manifest] = {}
        self._handlers: dict[str, list] = {}
        self._loaded = False

    def module_id_for(self, dotted_name: str) -> str:
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
        module_id = self.module_id_for(func.__module__)
        if module_id != "core":
            manifest = self._manifests.get(module_id)
            if manifest is None or event not in manifest.subscribes:
                raise RegistryError(
                    f"handler for {event!r} is not declared in {module_id!r} subscribes"
                )
        self._handlers.setdefault(event, []).append(func)

    def subscribe(self, event: str):
        def decorator(func):
            self.add_handler(event, func)
            return func

        return decorator

    def load_packages(self, packages) -> None:
        import importlib.util
        import json
        from pathlib import Path

        for package in packages:
            spec = importlib.util.find_spec(package)
            if spec is None or not spec.submodule_search_locations:
                raise RegistryError(f"module package {package!r} not found")
            manifest_path = Path(next(iter(spec.submodule_search_locations))) / "manifest.json"
            from easybiz.core.kernel.manifest import parse_manifest

            data = json.loads(manifest_path.read_text())
            self.add(parse_manifest(data, package=package))
        self.load_order()

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        from django.conf import settings

        self.load_packages(settings.EASYBIZ_MODULE_PACKAGES)
        self._loaded = True

    def verify_apps(self) -> None:
        from django.apps import apps

        for mid, manifest in self._manifests.items():
            app = apps.get_app_config(mid)  # label must equal id
            if app.name != manifest.package:
                raise RegistryError(
                    f"app {mid!r} name {app.name!r} != package {manifest.package!r}"
                )

    def import_module_code(self) -> None:
        import importlib

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
```

(Add `import importlib.util` at module top for `import_module_code`'s `find_spec`.)

- [ ] **Step 4: Create `contracts.py`**

```python
"""Capability contracts: versioned Protocols a module can provide/consume."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class AttendanceProvider(Protocol):
    """Approved working hours for a user in a date range (provided by Timesheets)."""

    def approved_hours(self, user_id: UUID, start: date, end: date) -> Decimal: ...
```

- [ ] **Step 5: Keep discovery explicit-list behaviour (entry points optional)**

`discovery.py` already returns the explicit list. Leave the `easybiz.modules` entry-point merge as-is for M2 (no packaged modules register entry points yet); the test only asserts the explicit list is returned. Do not change behaviour unless the test fails.

- [ ] **Step 6: Wire `apps.py::ready()`**

```python
from django.apps import AppConfig


class KernelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easybiz.core.kernel"
    label = "kernel"

    def ready(self) -> None:
        """Load and validate module manifests at startup (M2)."""
        from easybiz.core.kernel.registry import registry

        registry.ensure_loaded()
        registry.verify_apps()
        registry.import_module_code()
```

- [ ] **Step 7: Run the targeted tests, then the whole suite + check**

Run: `uv run pytest tests/test_manifest_and_registry.py -v`
Expected: PASS.
Run: `uv run manage.py check && uv run pytest`
Expected: `check` clean (registry loads the timesheets manifest, verify_apps passes, no handlers/providers to import); full suite green. If `ready()` raises during `check`, read the error — a real timesheets manifest/app mismatch is a finding; fix the manifest or app, not the kernel.

- [ ] **Step 8: Gate + commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy easybiz config`
Expected: clean.

```bash
git add easybiz/core/kernel tests/test_manifest_and_registry.py
git commit -m "Add registry runtime wiring, contracts, and startup load"
```

---

### Task 5: README + milestone close

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Update Status to: **M2 (kernel core) — complete.** Manifest validation, version ranges, the module registry (dependency graph/load order), discovery, and capability contracts are in place and loaded at startup; `state.py`/`capabilities.py` deferred to M3. Keep the command list current.

- [ ] **Step 2: Full gate**

Run: `uv run pytest && uv run ruff check . && uv run mypy easybiz config && uv run manage.py makemigrations --check --dry-run`
Expected: all green; `No changes detected` (M2 adds no models).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document M2 kernel core in README"
```

---

## M2 Definition of Done

- [ ] `tests/test_manifest_and_registry.py` passes (version truth table, manifest validation, load order/missing/incompatible/cycle, dependents_of, module_id_for, add_handler, discovery) — ~26 tests, no DB.
- [ ] `registry.ensure_loaded()` + `verify_apps()` + `import_module_code()` run at startup; `uv run manage.py check` and the full suite stay green.
- [ ] `RegistryError` messages contain `"not installed"`, the found version, or `"cycle"` as applicable.
- [ ] `state.py`/`capabilities.py` deferred to M3 (documented); `contracts.py` defines `AttendanceProvider`.
- [ ] `ruff` + `mypy easybiz config` clean; README reflects M2; commits short, no attribution.
