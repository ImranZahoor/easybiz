# F17a — Module System v2: Manifest v2, Validation Gaps, Capability Versioning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce manifest v2 (versioned `provides`/`consumes`, `requires_core`, extension-point declarations, `sensitive` permissions), close the three manifest validation gaps, and make capability resolution version-aware — all dependency-free and backward compatible with v1 manifests.

**Architecture:** `parse_manifest` grows hand-rolled v2 structural validation and normalises both v1 (bare-string) and v2 (object) `provides`/`consumes` into typed tuples on the `Manifest` dataclass. A published `manifest.schema.json` documents the shape; a test keeps its top-level keys in sync with what the parser accepts (no `jsonschema` dependency — the parser is the enforcement). The registry gains cross-cutting checks (contract names exist, consumes optionality, declared provides are actually registered, `requires_core` satisfied). `capabilities.register/get` carry a semver version/range resolved with the existing `Version`/`VersionRange`; an incompatible provider is treated as unavailable and logged.

**Tech Stack:** Python 3.13, Django 6.1, django-tenants, stdlib `logging`, `uv`/pytest on real PostgreSQL. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §20 (F17) items 2 (manifest v2), 3 (validation gaps), 4 (capability versioning), and the F17a delivery-slice note in that section. F17b (extension-point *runtime*), F17c (contract test kit), F17d (scaffold/uninstall) are later slices.

## Global Constraints

- **No new dependencies** (user decision): v2 structural validation is hand-rolled in `parse_manifest`; `manifest.schema.json` is the published contract, not a runtime validator.
- **Backward compatible**: a manifest with no `manifest_version` (or `1`) keeps loading; its bare-string `provides`/`consumes` still work. Only `manifest_version: 2` unlocks the object forms and new keys.
- Semver uses the **existing** `Version`/`VersionRange` in `manifest.py` — no other version library.
- Core/module boundary unchanged (I1/I2); contracts live in `easybiz/core/contracts.py`.
- `manifest.permissions` stays a `(code, description)` tuple list (lifecycle seeds from it); the `sensitive` flag lives in a **separate** `Manifest.sensitive_permissions` field.
- Enforcement note (deliberate deviation from the spec's literal "JSON Schema … enforced at load"): the hand-rolled parser is the enforcement; `manifest.schema.json` is the published/documented contract, kept honest by a sync test.

## Review Focus

- **v1 manifest still loads** — a manifest with no `manifest_version` and bare-string `provides`/`consumes` (e.g. the `demo` module) parses and loads unchanged. (Task 2.)
- **`provides`/`consumes` naming an unknown contract** — a contract name absent from `easybiz/core/contracts.py` is rejected at registry load, not silently ignored. (Task 5.)
- **Non-optional unsatisfiable `consumes`** — a `consumes` entry not marked `optional` whose contract no `requires` module `provides` is rejected at load. (Task 5.)
- **Provider version outside the consumer's range** — `get(contract, range=...)` treats an out-of-range provider as unavailable (returns `None`/raises as if disabled) and logs it, rather than returning an incompatible impl. (Task 4.)
- **`manifest.schema.json` drifting from the parser** — the published schema's top-level property names and the parser's accepted keys are asserted equal, so the doc can't rot silently. (Task 3.)

---

### Task 1: Contract version marker + core version setting

**Files:**
- Modify: `easybiz/core/contracts.py`
- Modify: `config/settings.py`
- Test: `tests/test_contract_version.py`

**Interfaces:**
- Produces: `AttendanceProvider.__contract_version__: str = "1.0.0"`; `settings.EASYBIZ_CORE_VERSION: str` (default `"1.0.0"`, overridable via the `EASYBIZ_CORE_VERSION` env var).

- [ ] **Step 1: Write the failing test**

```python
from django.conf import settings
from easybiz.core.contracts import AttendanceProvider

def test_contract_declares_version():
    assert AttendanceProvider.__contract_version__ == "1.0.0"

def test_core_version_setting():
    assert settings.EASYBIZ_CORE_VERSION == "1.0.0"
```

- [ ] **Step 2: Run it, verify it fails** — Run: `uv run pytest tests/test_contract_version.py -q` — Expected: FAIL (attribute / setting missing).
- [ ] **Step 3: Implement** — add `__contract_version__ = "1.0.0"` to `AttendanceProvider`; add `EASYBIZ_CORE_VERSION = os.environ.get("EASYBIZ_CORE_VERSION", "1.0.0")` to `config/settings.py` (near the other `EASYBIZ_*` settings).
- [ ] **Step 4: Run it, verify it passes** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/contracts.py config/settings.py tests/test_contract_version.py && git commit -m "Add __contract_version__ and EASYBIZ_CORE_VERSION"`

---

### Task 2: Manifest v2 parsing

**Files:**
- Modify: `easybiz/core/kernel/manifest.py`
- Modify: `easybiz/core/platform_api/queries.py:111` (map tuple `provides` back to contract-name strings for the API)
- Test: `tests/test_manifest_v2.py`

**Interfaces:**
- Produces (new/changed on `Manifest`):
  - `manifest_version: int = 1`
  - `requires_core: str | None = None`
  - `provides: list[tuple[str, str]]` — `(contract, version)` (was `list[str]`)
  - `consumes: list[tuple[str, str, bool]]` — `(contract, range, optional)` (was `list[str]`)
  - `sensitive_permissions: frozenset[str] = frozenset()`
  - `extension_points: list[dict]` — each validated to `{name, contract, version}`
  - `extends: list[dict]` — each validated to contain `point`
  - `permissions` unchanged (`list[tuple[str, str]]`)
  - module constant `KNOWN_KEYS: frozenset[str]` — the top-level manifest keys the parser reads.
- Normalisation: v1 (no `manifest_version` / `1`) → bare-string `provides` become `(s, "1.0.0")`, bare-string `consumes` become `(s, "*", False)`. v2 requires object forms; a bare string in a v2 `provides`/`consumes` is a `ManifestError`.
- `to_dict` serialises the new tuple/field shapes; `platform_api/queries.py` emits `provides=[c for c, _ in manifest.provides]`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from easybiz.core.kernel.manifest import ManifestError, parse_manifest

def test_v1_manifest_backward_compatible():
    m = parse_manifest({"id": "demo", "name": "Demo", "version": "0.1.0",
                        "provides": ["AttendanceProvider"], "consumes": ["Foo"]})
    assert m.manifest_version == 1
    assert m.provides == [("AttendanceProvider", "1.0.0")]
    assert m.consumes == [("Foo", "*", False)]

def test_v2_provides_consumes_objects():
    m = parse_manifest({
        "id": "hr", "name": "HR", "version": "1.0.0", "manifest_version": 2,
        "requires_core": "^1.0",
        "provides": [{"contract": "EmployeeProvider", "version": "1.2.0"}],
        "consumes": [{"contract": "AttendanceProvider", "range": "^1.0", "optional": True}],
        "extension_points": [{"name": "hr.leave_validator", "contract": "LeaveValidator", "version": "1.0.0"}],
        "extends": [{"point": "demo.thing"}],
        "permissions": [{"code": "hr.pay.read", "description": "x", "sensitive": True}],
    })
    assert m.manifest_version == 2 and m.requires_core == "^1.0"
    assert m.provides == [("EmployeeProvider", "1.2.0")]
    assert m.consumes == [("AttendanceProvider", "^1.0", True)]
    assert m.extension_points[0]["name"] == "hr.leave_validator"
    assert m.extends[0]["point"] == "demo.thing"
    assert m.sensitive_permissions == frozenset({"hr.pay.read"})

def test_v2_rejects_bare_string_provides():
    with pytest.raises(ManifestError):
        parse_manifest({"id": "hr", "name": "HR", "version": "1.0.0",
                        "manifest_version": 2, "provides": ["EmployeeProvider"]})

def test_v2_rejects_bad_extension_point_and_bad_sensitive_and_bad_requires_core():
    base = {"id": "hr", "name": "HR", "version": "1.0.0", "manifest_version": 2}
    with pytest.raises(ManifestError):
        parse_manifest({**base, "extension_points": [{"contract": "X"}]})       # missing name
    with pytest.raises(ManifestError):
        parse_manifest({**base, "permissions": [{"code": "hr.x", "sensitive": "yes"}]})  # non-bool
    with pytest.raises(ManifestError):
        parse_manifest({**base, "requires_core": "not-a-range"})

def test_v2_accepts_and_ignores_forward_declared_keys():
    # keys for unbuilt features (F5-F18) must not break loading; they are simply not surfaced yet
    m = parse_manifest({"id": "hr", "name": "HR", "version": "1.0.0", "manifest_version": 2,
                        "settings": [{"key": "x"}], "jobs": [], "ui": {"menu": []}})
    assert m.manifest_version == 2  # parsed fine, forward-declared keys ignored
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_manifest_v2.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the dataclass fields, `KNOWN_KEYS`, v1/v2 normalisation and hand-rolled v2 structural validation in `parse_manifest` (helpers `_provides(raw, mv)`, `_consumes(raw, mv)`, `_extension_points(raw)`, `_extends(raw)`), update `to_dict`, and change `platform_api/queries.py:111` to `provides=[c for c, _ in manifest.provides]`.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Guard existing callers** — Run: `uv run pytest tests/test_manifest_and_registry.py tests/test_platform_modules.py -q` — Expected: PASS (adjust only if an assertion pinned the old `provides`/`consumes` shape).
- [ ] **Step 6: Commit** — `git add easybiz/core/kernel/manifest.py easybiz/core/platform_api/queries.py tests/test_manifest_v2.py && git commit -m "Parse manifest v2 (versioned provides/consumes, requires_core, extension points, sensitive)"`

---

### Task 3: Published manifest schema + sync test

**Files:**
- Create: `easybiz/core/kernel/manifest.schema.json`
- Test: `tests/test_manifest_schema_sync.py`

**Interfaces:**
- Consumes: `manifest.KNOWN_KEYS` (Task 2 — the live keys the parser reads).
- Produces: a JSON Schema (draft-07, `type: object`) documenting the full v2 surface — every live key plus the forward-declared keys (`settings`, `jobs`, `numbering`, `workflows`, `custom_fields`, `ui`) that later features (F5–F18) will populate. Every live key the parser reads must appear; forward-declared keys may appear in addition. Published contract only; not executed at runtime.

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path
from easybiz.core.kernel import manifest

def test_schema_documents_every_parsed_key():
    schema = json.loads((Path(manifest.__file__).parent / "manifest.schema.json").read_text())
    props = set(schema["properties"])
    assert set(manifest.KNOWN_KEYS) <= props            # every parsed key is documented
    assert {"settings", "jobs", "ui"} <= props          # forward-declared keys are documented too
```

- [ ] **Step 2: Run it, verify it fails** — Run: `uv run pytest tests/test_manifest_schema_sync.py -q` — Expected: FAIL (file missing).
- [ ] **Step 3: Write `manifest.schema.json`** with a `properties` entry for every key in `KNOWN_KEYS` (typed, with the item-object shapes for `provides`/`consumes`/`extension_points`/`extends`/`permissions`) **and** the forward-declared keys (`settings`/`jobs`/`numbering`/`workflows`/`custom_fields`/`ui`) documented permissively. `required: ["id", "name", "version"]`.
- [ ] **Step 4: Run it, verify it passes** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/kernel/manifest.schema.json tests/test_manifest_schema_sync.py && git commit -m "Publish manifest.schema.json with a parser sync test"`

---

### Task 4: Version-aware capability resolution

**Files:**
- Modify: `easybiz/core/kernel/capabilities.py`
- Test: `tests/test_capability_versioning.py`

**Interfaces:**
- Consumes: `Version`, `VersionRange` from `manifest.py`.
- Produces:
  - `register(contract, impl, module_id, version="1.0.0")` — stores `(impl, module_id, version)`.
  - `get(contract, range=None, optional=False)` — resolves the provider; if `range` is given and the stored version is not in `VersionRange.parse(range)`, log a warning via `logging.getLogger("easybiz.capabilities")` and treat as unavailable (return `None` if `optional`, else raise `CapabilityUnavailable`). The tenant-enabled check is unchanged and still applies first.
  - `provider_meta(contract) -> tuple[str, str] | None` — `(module_id, version)` if registered, else `None` (used by the registry in Task 5).
- Back-compat: `version`/`range` are optional, so `register(c, impl, "demo")` and `get(c, optional=True)` keep working.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from django_tenants.utils import tenant_context
from easybiz.core.kernel import capabilities, lifecycle

class _C: pass
class _Impl: pass

def test_in_range_provider_returned(synced, db_tenant):
    impl = _Impl()
    capabilities.register(_C, impl, "demo", version="1.3.0")
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        assert capabilities.get(_C, range="^1.0") is impl

def test_out_of_range_provider_unavailable(synced, db_tenant):
    impl = _Impl()
    capabilities.register(_C, impl, "demo", version="2.0.0")
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        assert capabilities.get(_C, range="^1.0", optional=True) is None
        with pytest.raises(capabilities.CapabilityUnavailable):
            capabilities.get(_C, range="^1.0")

def test_provider_meta():
    capabilities.register(_C, _Impl(), "demo", version="1.3.0")
    assert capabilities.provider_meta(_C) == ("demo", "1.3.0")
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_capability_versioning.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the version field, range resolution with a logged warning on mismatch, and `provider_meta`.
- [ ] **Step 4: Run them + the existing capability tests** — Run: `uv run pytest tests/test_capability_versioning.py tests/test_capabilities.py -q` — Expected: PASS (old 3-arg `register`/range-less `get` still work).
- [ ] **Step 5: Commit** — `git add easybiz/core/kernel/capabilities.py tests/test_capability_versioning.py && git commit -m "Make capability resolution version-aware (register version, get range)"`

---

### Task 5: Registry validation gaps + requires_core

**Files:**
- Modify: `easybiz/core/kernel/registry.py`
- Test: `tests/test_module_validation.py`

**Interfaces:**
- Consumes: `Manifest` (Task 2 shapes), `capabilities.provider_meta` (Task 4), `settings.EASYBIZ_CORE_VERSION` (Task 1), `easybiz.core.contracts`.
- Produces (new private checks, run inside the existing load path):
  - `_assert_requires_core()` — each manifest's `requires_core` (if set) must contain `Version.parse(settings.EASYBIZ_CORE_VERSION)`; run in `load_order` alongside `_assert_requirements`.
  - `_assert_contracts_exist()` — every `provides`/`consumes` contract name must be an attribute of `easybiz.core.contracts`; run in `load_order`.
  - `_assert_consumes_satisfiable()` — for each manifest, every `consumes` entry with `optional=False` must be `provides`-declared by one of that module's `requires` targets; else `RegistryError`; run in `load_order`.
  - `_assert_provides_registered()` — each `provides (contract, version)` must have `capabilities.provider_meta(getattr(contracts, name))` returning `(this_module_id, version)`; run at the end of `import_module_code` (after providers import).
- Errors raised are `RegistryError` (consistent with existing graph errors).
- Scope: `_assert_consumes_satisfiable` checks only *existence* (a `requires` target declares the contract in `provides`) and optionality — it does **not** match the provider's version against the consumer's `range`. Version resolution is the runtime job of `capabilities.get(contract, range=...)` (Task 4), per spec item 4 ("the registry resolves … incompatible provider counts as unavailable").

- [ ] **Step 1: Write the failing tests** (use the real `Registry` with synthetic manifests; `AttendanceProvider` is a real contract name, bogus names exercise the negative paths)

```python
import pytest
from easybiz.core.kernel import capabilities
from easybiz.core.kernel.manifest import parse_manifest
from easybiz.core.kernel.registry import Registry, RegistryError
from easybiz.core.contracts import AttendanceProvider

def _reg(*manifests):
    r = Registry()
    for data in manifests:
        r.add(parse_manifest(data, package=f"pkg.{data['id']}"))
    return r

V2 = {"manifest_version": 2, "version": "1.0.0"}

def test_provides_unknown_contract_rejected():
    r = _reg({**V2, "id": "hr", "name": "HR", "provides": [{"contract": "Nope"}]})
    with pytest.raises(RegistryError):
        r.load_order()

def test_consumes_unknown_contract_rejected():
    r = _reg({**V2, "id": "hr", "name": "HR", "consumes": [{"contract": "Nope", "optional": True}]})
    with pytest.raises(RegistryError):
        r.load_order()

def test_non_optional_unsatisfiable_consume_rejected():
    # hr consumes AttendanceProvider (real) but no required module provides it
    r = _reg({**V2, "id": "hr", "name": "HR", "consumes": [{"contract": "AttendanceProvider"}]})
    with pytest.raises(RegistryError):
        r.load_order()

def test_optional_unsatisfiable_consume_ok():
    r = _reg({**V2, "id": "hr", "name": "HR",
              "consumes": [{"contract": "AttendanceProvider", "optional": True}]})
    r.load_order()  # no raise

def test_requires_core_incompatible_rejected():
    r = _reg({**V2, "id": "hr", "name": "HR", "requires_core": ">=99.0"})
    with pytest.raises(RegistryError):
        r.load_order()

def test_provides_not_registered_rejected():
    # declares it provides AttendanceProvider but nothing registered it for "hr"
    r = _reg({**V2, "id": "hr", "name": "HR",
              "provides": [{"contract": "AttendanceProvider", "version": "1.0.0"}]})
    with pytest.raises(RegistryError):
        r._assert_provides_registered()  # the post-import check, called directly
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_module_validation.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the four checks and wire `_assert_requires_core`/`_assert_contracts_exist`/`_assert_consumes_satisfiable` into `load_order`, and `_assert_provides_registered` into `import_module_code`.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/kernel/registry.py tests/test_module_validation.py && git commit -m "Close manifest validation gaps and enforce requires_core"`

---

### Task 6: Timesheets manifest → v2 (end-to-end proof)

**Files:**
- Modify: `easybiz/modules/timesheets/manifest.json`
- Modify: `easybiz/modules/timesheets/providers.py` (register `AttendanceProvider` with its version)
- Test: `tests/test_module_v2_integration.py`

**Interfaces:**
- Consumes: Tasks 2/4/5.
- Behaviour: timesheets becomes `manifest_version: 2` and declares `provides: [{"contract": "AttendanceProvider", "version": "1.0.0"}]`; `providers.py` calls `capabilities.register(AttendanceProvider, TimesheetsAttendance(), "timesheets", version="1.0.0")`. `demo` stays v1 (back-compat proof). The real registry must load clean (`_assert_provides_registered` passes for timesheets).

- [ ] **Step 1: Write the failing test**

```python
from easybiz.core.kernel.registry import registry

def test_real_modules_load_with_v2_timesheets(synced):
    registry.ensure_loaded()
    registry.import_module_code()
    registry._assert_provides_registered()  # timesheets provides AttendanceProvider, registered
    ts = registry.manifest("timesheets")
    assert ts.manifest_version == 2 and ("AttendanceProvider", "1.0.0") in ts.provides
    assert registry.manifest("demo").manifest_version == 1  # demo still v1
```

- [ ] **Step 2: Run it, verify it fails** — Run: `uv run pytest tests/test_module_v2_integration.py -q` — Expected: FAIL (timesheets still v1 / provides empty).
- [ ] **Step 3: Implement** the timesheets manifest + providers change.
- [ ] **Step 4: Run it, verify it passes** — Expected: PASS.
- [ ] **Step 5: Run the full suite** — Run: `uv run pytest -q` — Expected: all pass.
- [ ] **Step 6: Commit** — `git add easybiz/modules/timesheets/manifest.json easybiz/modules/timesheets/providers.py tests/test_module_v2_integration.py && git commit -m "Adopt manifest v2 in timesheets (declares AttendanceProvider)"`

---

## Post-implementation
- Update `README.md` Status with a short F17a paragraph (manifest v2, validation gaps, capability versioning; dependency-free).
- No new events; no Appendix D change.
- This is authz-adjacent only at the edges (module gating), not core authz — a security review is optional here; the standard whole-branch review still applies.
