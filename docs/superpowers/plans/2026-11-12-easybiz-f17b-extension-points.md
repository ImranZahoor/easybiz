# F17b — Module System v2: Extension Points — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add in-process extension points — the multi-provider sibling of capabilities — so a module can contribute to another module's defined hooks, gated per tenant and validated at load, proven against a trivial `demo` point.

**Architecture:** `easybiz/core/kernel/extensions.py` holds a process-global `point name → [(impl, module_id)]` map. `register(point, impl, module_id)` appends (many per point); `contributors(point)` returns the impls whose module is enabled for `connection.tenant`, in registry dependency/load order — and nothing else (the host owns the all-pass / collect / first-wins semantics at its own hook). The registry validates the `extension_points`/`extends` declarations F17a already parses: a host point's contract must exist; a point name must be unique; an extender's `extends[].point` must name a declared point of a module it `requires`/`optional`s, with a compatible version. The `demo` module declares one trivial point and a host-side fan-out helper; the extender side is proven by registering synthetic contributors under real (enableable) module ids.

**Tech Stack:** Python 3.13, Django 6.1, django-tenants, stdlib only. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §20 (F17) item 4a (extension points) and the F17b slice note. F17c (contract test kit), F17d (scaffold/uninstall) follow. Builds on F17a (manifest v2 already parses `extension_points`/`extends`; `capabilities`/`__contract_version__`/validation gaps exist).

## Global Constraints

- No new dependencies. `extensions.py` mirrors `capabilities.py`: process-global dict, per-tenant gating via `state.is_enabled(connection.tenant, module_id)`.
- `extensions.contributors` is **semantics-free** — it returns the enabled contributors in load order; the host module decides how to combine them (I1/I2: contributors interact only through the Protocol and plain values; no cross-module imports/FKs).
- Point versioning is validated at **load** (extender's declared range vs the point's version); `contributors()` does not re-filter by version at runtime (an incompatible extender never loads).
- Imports at top of file (repo convention); the one allowed exception is a lazy import to break a kernel import cycle, with a one-line comment.
- Backward compatible: modules with no `extension_points`/`extends` are unaffected.

## Review Focus

- **A disabled contributor is excluded** — `contributors(point)` must omit a registered contributor whose module is not enabled for the current tenant (gated like capabilities/I7). (Task 1.)
- **Contributor order is deterministic** — `contributors(point)` returns impls in registry dependency/load order, not registration order. (Task 1.)
- **`extends` a point of a non-depended module** — an `extends[].point` whose host is not in the extender's `requires`/`optional` is rejected at load. (Task 2.)
- **`extends` version mismatch** — an `extends` entry whose declared `range` does not contain the point's version is rejected at load. (Task 2.)
- **Duplicate point name** — two modules declaring the same `extension_points[].name` is rejected as ambiguous. (Task 2.)

---

### Task 1: The extensions runtime

**Files:**
- Create: `easybiz/core/kernel/extensions.py`
- Modify: `tests/conftest.py` (add an autouse `_reset_extensions` fixture mirroring `_reset_capabilities`)
- Test: `tests/test_extensions.py`

**Interfaces:**
- Consumes: `state.is_enabled`, `connection.tenant`, `registry.load_order()`.
- Produces:
  - module-global `_contributors: dict[str, list[tuple[object, str]]]` (point name → `[(impl, module_id), ...]`).
  - `register(point: str, impl: object, module_id: str) -> None` — append (many per point).
  - `contributors(point: str) -> list` — impls whose `module_id` is enabled for `connection.tenant`, ordered by `registry.load_order()`; `[]` when there is no tenant or no enabled contributor.
- conftest `_reset_extensions` saves/restores `extensions._contributors` around each test (process-global isolation), exactly like `_reset_capabilities`.

- [ ] **Step 1: Write the failing tests** (register under the real module ids `demo`/`timesheets`, which are enableable)

```python
from django_tenants.utils import tenant_context
from easybiz.core.kernel import extensions, lifecycle

class _G:
    def __init__(self, tag): self.tag = tag

def test_only_enabled_contributors(synced, db_tenant):
    extensions.register("demo.p", _G("d"), "demo")
    extensions.register("demo.p", _G("t"), "timesheets")
    lifecycle.enable_module(db_tenant, "demo")  # timesheets not enabled
    with tenant_context(db_tenant):
        assert [g.tag for g in extensions.contributors("demo.p")] == ["d"]

def test_contributors_in_load_order(synced, db_tenant):
    extensions.register("demo.p", _G("t"), "timesheets")
    extensions.register("demo.p", _G("d"), "demo")  # registered after, but demo sorts first
    lifecycle.enable_module(db_tenant, "demo")
    lifecycle.enable_module(db_tenant, "timesheets")
    with tenant_context(db_tenant):
        assert [g.tag for g in extensions.contributors("demo.p")] == ["d", "t"]  # load order

def test_no_tenant_no_contributors():
    extensions.register("demo.p", _G("d"), "demo")
    assert extensions.contributors("demo.p") == []

def test_unknown_point_is_empty():
    assert extensions.contributors("nope") == []
```

(`demo` precedes `timesheets` in `registry.load_order()` — both are independent, so order is the sorted id order; the test asserts that exact order.)

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_extensions.py -q` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement `extensions.py`** — `contributors` filters by `state.is_enabled(tenant, module_id)` then sorts by `registry.load_order().index(module_id)`.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/kernel/extensions.py tests/conftest.py tests/test_extensions.py && git commit -m "Add extension-point runtime (register/contributors, per-tenant gated)"`

---

### Task 2: Registry validation for extension points

**Files:**
- Modify: `easybiz/core/kernel/registry.py`
- Test: `tests/test_extension_validation.py`

**Interfaces:**
- Consumes: `Manifest.extension_points` / `Manifest.extends` (F17a shapes), `Version`/`VersionRange`, the `_is_contract` check used by `_assert_contracts_exist`.
- Produces (run inside `load_order`, after the F17a checks):
  - extend `_assert_contracts_exist` (or a sibling) so every `extension_points[].contract` must also be a real contract in `easybiz.core.contracts`.
  - `_points_index() -> dict[str, tuple[str, str]]` — `point name → (host_module_id, version)` across all manifests; raises `RegistryError` on a duplicate name.
  - `_assert_extends_valid()` — for each manifest `m` and each `ext` in `m.extends`: the point must exist in the index; its host must be in `m`'s `requires`/`optional` ids; if `ext` has a `range`, `VersionRange.parse(ext["range"])` must contain `Version.parse(point_version)`; else `RegistryError`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from easybiz.core.kernel.manifest import parse_manifest
from easybiz.core.kernel.registry import Registry, RegistryError

V2 = {"manifest_version": 2, "version": "1.0.0"}
POINT = {"name": "demo.p", "contract": "AttendanceProvider", "version": "1.0.0"}

def _reg(*manifests):
    r = Registry()
    for d in manifests:
        r.add(parse_manifest(d, package=f"pkg.{d['id']}"))
    return r

def test_extension_point_unknown_contract_rejected():
    r = _reg({**V2, "id": "demo", "name": "D",
              "extension_points": [{"name": "demo.p", "contract": "Nope"}]})
    with pytest.raises(RegistryError):
        r.load_order()

def test_extends_unknown_point_rejected():
    r = _reg({**V2, "id": "hr", "name": "HR", "extends": [{"point": "demo.p"}]})
    with pytest.raises(RegistryError):
        r.load_order()

def test_extends_requires_host():
    host = {**V2, "id": "demo", "name": "D", "extension_points": [POINT]}
    # hr extends demo.p but does NOT require/optional demo
    ext = {**V2, "id": "hr", "name": "HR", "extends": [{"point": "demo.p"}]}
    with pytest.raises(RegistryError):
        _reg(host, ext).load_order()

def test_extends_valid_when_host_required():
    host = {**V2, "id": "demo", "name": "D", "extension_points": [POINT]}
    ext = {**V2, "id": "hr", "name": "HR", "requires": [{"module": "demo"}],
           "extends": [{"point": "demo.p"}]}
    _reg(host, ext).load_order()  # no raise

def test_extends_version_mismatch_rejected():
    host = {**V2, "id": "demo", "name": "D", "extension_points": [POINT]}  # version 1.0.0
    ext = {**V2, "id": "hr", "name": "HR", "requires": [{"module": "demo"}],
           "extends": [{"point": "demo.p", "range": ">=2.0"}]}
    with pytest.raises(RegistryError):
        _reg(host, ext).load_order()

def test_duplicate_point_name_rejected():
    a = {**V2, "id": "demo", "name": "D", "extension_points": [POINT]}
    b = {**V2, "id": "timesheets", "name": "T", "extension_points": [POINT]}
    with pytest.raises(RegistryError):
        _reg(a, b).load_order()
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_extension_validation.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the contract-existence extension, `_points_index`, and `_assert_extends_valid`, wired into `load_order`.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/kernel/registry.py tests/test_extension_validation.py && git commit -m "Validate extension_points/extends declarations"`

---

### Task 3: Demo extension point (end-to-end proof)

**Files:**
- Modify: `easybiz/core/contracts.py` (add the `DemoGreeter` point contract)
- Modify: `easybiz/modules/demo/manifest.json` (→ `manifest_version: 2`, declare the point)
- Create: `easybiz/modules/demo/greetings.py` (host-side fan-out helper)
- Modify: `tests/test_module_v2_integration.py` (demo is now v2)
- Test: `tests/test_demo_extension_point.py`

**Interfaces:**
- Produces:
  - `contracts.DemoGreeter` — a `runtime_checkable` `Protocol` with `__contract_version__ = "1.0.0"` and `def greet(self) -> str: ...`.
  - demo manifest: `manifest_version: 2`, `extension_points: [{"name": "demo.greeters", "contract": "DemoGreeter", "version": "1.0.0"}]`.
  - `easybiz/modules/demo/greetings.py`: `def all_greetings() -> list[str]: return [g.greet() for g in extensions.contributors("demo.greeters")]`.

- [ ] **Step 1: Write the failing tests**

```python
from django_tenants.utils import tenant_context
from easybiz.core.kernel import extensions, lifecycle
from easybiz.modules.demo.greetings import all_greetings

class _Hi:
    def greet(self): return "hi"

def test_demo_point_collects_enabled_contributors(synced, db_tenant):
    extensions.register("demo.greeters", _Hi(), "demo")
    with tenant_context(db_tenant):
        assert all_greetings() == []          # demo not enabled yet
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        assert all_greetings() == ["hi"]      # enabled contributor shows up
```

Also update `tests/test_module_v2_integration.py`: change the `demo` assertion to `registry.manifest("demo").manifest_version == 2` and assert the point is declared (`any(ep["name"] == "demo.greeters" for ep in registry.manifest("demo").extension_points)`). (v1 back-compat remains proven by `tests/test_manifest_v2.py::test_v1_manifest_backward_compatible`.)

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_demo_extension_point.py tests/test_module_v2_integration.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the `DemoGreeter` contract, the demo manifest change, `greetings.py`, and the integration-test update.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Run the full suite** — Run: `uv run pytest -q` — Expected: all pass.
- [ ] **Step 6: Commit** — `git add easybiz/core/contracts.py easybiz/modules/demo/manifest.json easybiz/modules/demo/greetings.py tests/test_demo_extension_point.py tests/test_module_v2_integration.py && git commit -m "Prove extension points against a demo point"`

---

## Post-implementation
- Update `README.md` Status with a short F17b paragraph (extension points: `register`/`contributors`, per-tenant gated, manifest `extension_points`/`extends` validated, demo proof).
- No new events; no migrations; no Appendix D change.
- Not core authz — a security review is optional; the standard whole-branch review applies.
